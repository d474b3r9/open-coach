"""Tests for the recovery monitor module (signals, assessment, adaptation)."""

from __future__ import annotations

from datetime import date
from typing import Literal

import pytest

from open_coach.models import WorkoutFeedback
from open_coach.recovery_monitor import (
    _RECOVERY_WEIGHTS,
    _score_hrv,
    _score_sleep,
    _score_stress,
    _score_subjective,
    _score_tsb,
    assess_recovery,
    recommend_adaptation,
)
from tests.conftest import make_planned_workout, make_profile

# ── Helpers ──────────────────────────────────────────────────────────────────

Feeling = Literal["great", "good", "okay", "tired", "terrible"]
Effort = Literal["too_easy", "easy", "moderate", "hard", "too_hard"]


def _feedback(feeling: Feeling = "good", effort: Effort = "moderate") -> WorkoutFeedback:
    return WorkoutFeedback(
        date=date.today(),
        workout_type="easy",
        feeling=feeling,
        perceived_effort=effort,
    )


# ── TestScoreHrv ─────────────────────────────────────────────────────────────


class TestScoreHrv:
    def test_above_baseline(self):
        s = _score_hrv(50.0, 48.0)
        assert s.status == "green"
        assert s.score == 1.0

    def test_slightly_suppressed(self):
        s = _score_hrv(43.0, 48.0)  # ratio ~0.896
        assert s.status == "yellow"
        assert s.score == 0.6

    def test_significantly_suppressed(self):
        s = _score_hrv(38.0, 48.0)  # ratio ~0.79
        assert s.status == "red"
        assert s.score == 0.3

    def test_missing_data(self):
        s = _score_hrv(None, None)
        assert s.status == "yellow"
        assert s.score == 0.5


# ── TestScoreSleep ───────────────────────────────────────────────────────────


class TestScoreSleep:
    def test_good_sleep(self):
        s = _score_sleep(85.0, 28800.0)  # 8h, score 85
        assert s.status == "green"
        assert s.score == 1.0

    def test_moderate_sleep(self):
        s = _score_sleep(65.0, 25200.0)  # 7h, score 65
        assert s.status == "yellow"
        assert s.score == 0.6

    def test_poor_sleep(self):
        s = _score_sleep(45.0, 25200.0)  # 7h, score 45
        assert s.status == "red"
        assert s.score == 0.3

    def test_short_duration_overrides_good_score(self):
        s = _score_sleep(90.0, 18000.0)  # 5h, score 90
        assert s.status == "red"
        assert s.score == 0.3

    def test_missing_data(self):
        s = _score_sleep(None, None)
        assert s.status == "yellow"
        assert s.score == 0.5


# ── TestScoreTsb ─────────────────────────────────────────────────────────────


class TestScoreTsb:
    def test_positive_tsb(self):
        s = _score_tsb(10.0)
        assert s.status == "green"
        assert s.score >= 0.7

    def test_slightly_negative(self):
        s = _score_tsb(-3.0)
        assert s.status == "yellow"
        assert s.score == 0.6

    def test_very_negative(self):
        s = _score_tsb(-15.0)
        assert s.status == "red"
        assert s.score == 0.25

    def test_missing(self):
        s = _score_tsb(None)
        assert s.status == "yellow"
        assert s.score == 0.5


# ── TestScoreStress ──────────────────────────────────────────────────────────


class TestScoreStress:
    def test_low_stress(self):
        s = _score_stress(20.0)
        assert s.status == "green"
        assert s.score == 1.0

    def test_moderate_stress(self):
        s = _score_stress(40.0)
        assert s.status == "yellow"
        assert s.score == 0.6

    def test_high_stress(self):
        s = _score_stress(65.0)
        assert s.status == "red"
        assert s.score == 0.3


# ── TestScoreSubjective ─────────────────────────────────────────────────────


class TestScoreSubjective:
    def test_great_feeling(self):
        fb = [_feedback(feeling="great", effort="easy")]
        s = _score_subjective(fb)
        assert s.status == "green"
        assert s.score >= 0.7

    def test_tired_feeling(self):
        fb = [_feedback(feeling="tired", effort="hard")]
        s = _score_subjective(fb)
        assert s.status == "red"
        assert s.score < 0.4

    def test_no_feedback(self):
        s = _score_subjective(None)
        assert s.status == "yellow"
        assert s.score == 0.5

    def test_multiple_entries_averaged(self):
        fb = [
            _feedback(feeling="great", effort="easy"),
            _feedback(feeling="tired", effort="hard"),
            _feedback(feeling="good", effort="moderate"),
        ]
        s = _score_subjective(fb)
        # Should be averaged, somewhere in the middle
        assert 0.4 <= s.score <= 0.7


# ── TestAssessRecovery ───────────────────────────────────────────────────────


class TestAssessRecovery:
    def test_all_green(self):
        r = assess_recovery(
            hrv_last_night=50.0,
            hrv_weekly_avg=48.0,
            sleep_score=85.0,
            sleep_duration_s=28800.0,
            tsb=10.0,
            avg_stress=20.0,
            recent_feedback=[_feedback("great", "easy")],
        )
        assert r.overall_score >= 70
        assert r.status == "green"

    def test_mixed_signals(self):
        r = assess_recovery(
            hrv_last_night=40.0,  # suppressed
            hrv_weekly_avg=48.0,
            sleep_score=85.0,  # good
            sleep_duration_s=28800.0,
            tsb=-3.0,  # yellow
            avg_stress=20.0,  # good
            recent_feedback=[_feedback("okay", "moderate")],
        )
        assert r.status == "yellow"

    def test_all_red(self):
        r = assess_recovery(
            hrv_last_night=30.0,
            hrv_weekly_avg=48.0,
            sleep_score=40.0,
            sleep_duration_s=18000.0,
            tsb=-15.0,
            avg_stress=70.0,
            recent_feedback=[_feedback("terrible", "too_hard")],
        )
        assert r.overall_score < 40
        assert r.status == "red"

    def test_missing_all_data(self):
        r = assess_recovery()
        # All defaults to yellow/0.5
        assert r.status == "yellow"
        assert r.overall_score == pytest.approx(50.0, abs=1.0)
        # Regression: missing data used to trigger alarming advice
        # ("HRV is suppressed", "you reported feeling tired"…) and name HRV as
        # "the main concern" although nothing was measured.
        assert r.recommendations == []
        assert all(not sig.available for sig in r.signals)
        assert "Not enough data" in r.summary

    def test_missing_signals_never_drive_summary_or_advice(self):
        r = assess_recovery(tsb=-15.0)  # only the load is known
        assert "tsb is the main concern" in r.summary.lower() or "tsb signals" in r.summary.lower()
        assert len(r.recommendations) == 1
        assert "fatigue" in r.recommendations[0].lower()

    def test_good_measured_signal_is_never_the_concern(self):
        # Regression: with only a positive TSB measured, the summary said
        # "tsb is the main concern" because missing signals made it yellow.
        r = assess_recovery(tsb=8.0)
        assert "concern" not in r.summary
        assert "Measured signals look good (TSB)" in r.summary
        assert "HRV" in r.summary

    def test_assessment_is_dated_with_the_requested_day(self):
        assert assess_recovery(today=date(2026, 9, 28)).date == date(2026, 9, 28)

    def test_weights_sum_to_one(self):
        total = sum(_RECOVERY_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_recommendations_generated_for_weak_signals(self):
        r = assess_recovery(
            hrv_last_night=30.0,
            hrv_weekly_avg=48.0,
            sleep_score=40.0,
            sleep_duration_s=18000.0,
            tsb=-15.0,
            avg_stress=70.0,
        )
        assert len(r.recommendations) > 0


# ── TestRecommendAdaptation ──────────────────────────────────────────────────


class TestRecommendAdaptation:
    def _green_recovery(self):
        return assess_recovery(
            hrv_last_night=50.0,
            hrv_weekly_avg=48.0,
            sleep_score=85.0,
            sleep_duration_s=28800.0,
            tsb=10.0,
            avg_stress=20.0,
            recent_feedback=[_feedback("great", "easy")],
        )

    def _yellow_recovery(self):
        return assess_recovery(
            hrv_last_night=42.0,
            hrv_weekly_avg=48.0,
            sleep_score=65.0,
            sleep_duration_s=23400.0,
            tsb=-3.0,
            avg_stress=35.0,
            recent_feedback=[_feedback("okay", "moderate")],
        )

    def _red_recovery(self):
        return assess_recovery(
            hrv_last_night=30.0,
            hrv_weekly_avg=48.0,
            sleep_score=40.0,
            sleep_duration_s=18000.0,
            tsb=-15.0,
            avg_stress=70.0,
            recent_feedback=[_feedback("terrible", "too_hard")],
        )

    def test_green_tempo_proceed(self):
        rec = recommend_adaptation(
            self._green_recovery(),
            make_planned_workout(wtype="tempo", description="Tempo 8km"),
            make_profile(),
        )
        assert rec.action == "proceed"

    def test_yellow_tempo_reduce(self):
        rec = recommend_adaptation(
            self._yellow_recovery(),
            make_planned_workout(wtype="tempo", description="Tempo 8km"),
            make_profile(),
        )
        assert rec.action == "reduce_intensity"

    def test_yellow_easy_proceed(self):
        rec = recommend_adaptation(
            self._yellow_recovery(),
            make_planned_workout(wtype="easy", description="Easy run"),
            make_profile(),
        )
        assert rec.action == "proceed"

    def test_yellow_long_run_reduce_volume(self):
        rec = recommend_adaptation(
            self._yellow_recovery(),
            make_planned_workout(wtype="long_run", description="Long run 20km", dist=20.0),
            make_profile(),
        )
        assert rec.action == "reduce_volume"

    def test_red_tempo_swap_to_easy(self):
        rec = recommend_adaptation(
            self._red_recovery(),
            make_planned_workout(wtype="tempo", description="Tempo 8km"),
            make_profile(),
        )
        assert rec.action == "swap_to_easy"

    def test_red_long_run_rest_day(self):
        rec = recommend_adaptation(
            self._red_recovery(),
            make_planned_workout(wtype="long_run", description="Long run 25km"),
            make_profile(),
        )
        assert rec.action == "rest_day"

    def test_red_easy_swap_to_easy(self):
        rec = recommend_adaptation(
            self._red_recovery(),
            make_planned_workout(wtype="easy", description="Easy run"),
            make_profile(),
        )
        assert rec.action == "swap_to_easy"

    def test_no_planned_workout_green(self):
        rec = recommend_adaptation(self._green_recovery(), None)
        assert rec.action == "proceed"

    def test_no_planned_workout_red(self):
        rec = recommend_adaptation(self._red_recovery(), None)
        assert rec.action == "rest_day"

    def test_adjusted_workout_has_content(self):
        rec = recommend_adaptation(
            self._yellow_recovery(),
            make_planned_workout(wtype="tempo", description="Tempo 8km", dist=8.0),
            make_profile(),
        )
        assert rec.adjusted_workout is not None
        assert len(rec.adjusted_workout) > 0

    def test_concrete_paces_with_vdot(self):
        rec = recommend_adaptation(
            self._red_recovery(),
            make_planned_workout(wtype="intervals", description="5x1000m"),
            make_profile(vdot=50.0),
        )
        assert rec.adjusted_workout is not None
        # Should contain pace info (format M:SS)
        assert "/km" in rec.adjusted_workout
