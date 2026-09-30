"""Tests for the race predictor module (predictions, pacing, readiness)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from open_coach.sports.running.race import (
    _confidence_band,
    assess_race_readiness,
    build_pacing_strategy,
    predict_race_times,
)
from open_coach.sports.running.vdot import predict_time
from tests.conftest import make_goal, make_plan, make_profile

# ── TestPredictRaceTimes ─────────────────────────────────────────────────────


class TestPredictRaceTimes:
    def test_returns_four_standard_distances(self):
        preds = predict_race_times(50.0)
        labels = [p.distance_label for p in preds]
        assert "5K" in labels
        assert "10K" in labels
        assert "Half Marathon" in labels
        assert "Marathon" in labels

    def test_includes_custom_distance(self):
        preds = predict_race_times(50.0, target_distance_m=15000.0)
        labels = [p.distance_label for p in preds]
        assert any("15" in label for label in labels)
        assert len(preds) == 5

    def test_custom_distance_near_standard_not_duplicated(self):
        preds = predict_race_times(50.0, target_distance_m=5050.0)
        assert len(preds) == 4  # 5050 is close to 5000, not added

    def test_confidence_widens_with_fatigue(self):
        fresh = predict_race_times(50.0, tsb=15.0)
        tired = predict_race_times(50.0, tsb=-15.0)
        # Tired prediction has wider band
        fresh_range = fresh[0].confidence_high_s - fresh[0].confidence_low_s
        tired_range = tired[0].confidence_high_s - tired[0].confidence_low_s
        assert tired_range > fresh_range

    def test_confidence_narrow_when_fresh(self):
        preds = predict_race_times(50.0, tsb=15.0)
        p5k = next(p for p in preds if p.distance_label == "5K")
        band_pct = (p5k.confidence_high_s - p5k.confidence_low_s) / p5k.predicted_time_s
        assert band_pct == pytest.approx(0.03, abs=0.005)  # ~3% total band

    def test_no_training_data_uses_default_band(self):
        preds = predict_race_times(50.0, tsb=None)
        p = preds[0]
        low_pct, _high_pct = _confidence_band(None)
        assert p.confidence_low_s == pytest.approx(p.predicted_time_s * (1 - low_pct), rel=0.001)

    def test_predictions_match_vdot_predict_time(self):
        preds = predict_race_times(50.0)
        for p in preds:
            expected = predict_time(50.0, p.distance_m)
            assert p.predicted_time_s == pytest.approx(expected, rel=0.001)

    def test_higher_vdot_faster_predictions(self):
        slow = predict_race_times(45.0)
        fast = predict_race_times(60.0)
        for s, f in zip(slow, fast, strict=False):
            assert f.predicted_time_s < s.predicted_time_s

    def test_pace_is_consistent(self):
        preds = predict_race_times(50.0)
        for p in preds:
            expected_pace = p.predicted_time_s / (p.distance_m / 1000.0)
            assert p.predicted_pace_sec_per_km == pytest.approx(expected_pace, rel=0.001)


# ── TestBuildPacingStrategy ──────────────────────────────────────────────────


class TestBuildPacingStrategy:
    def test_5k_auto_selects_even_effort(self):
        ps = build_pacing_strategy(5000.0, 1200.0)
        assert ps.strategy_name == "even_effort"

    def test_10k_auto_selects_slight_negative(self):
        ps = build_pacing_strategy(10000.0, 2400.0)
        assert ps.strategy_name == "slight_negative"

    def test_half_auto_selects_negative_split(self):
        ps = build_pacing_strategy(21097.5, 5400.0)
        assert ps.strategy_name == "negative_split"

    def test_marathon_auto_selects_conservative(self):
        ps = build_pacing_strategy(42195.0, 12600.0)
        assert ps.strategy_name == "conservative_start"

    def test_5k_has_per_km_splits(self):
        ps = build_pacing_strategy(5000.0, 1200.0)
        assert len(ps.splits) == 5

    def test_10k_has_per_km_splits(self):
        ps = build_pacing_strategy(10000.0, 2400.0)
        assert len(ps.splits) == 10

    def test_half_has_5k_block_splits(self):
        ps = build_pacing_strategy(21097.5, 5400.0)
        assert len(ps.splits) == 5  # 4 x 5K + final

    def test_marathon_has_9_splits(self):
        ps = build_pacing_strategy(42195.0, 12600.0)
        assert len(ps.splits) == 9  # 8 x 5K + final 2.195K

    def test_cumulative_time_close_to_target(self):
        ps = build_pacing_strategy(10000.0, 2400.0)
        last = ps.splits[-1]
        assert last.cumulative_time_s == pytest.approx(2400.0, rel=0.02)

    def test_splits_sum_to_distance(self):
        ps = build_pacing_strategy(42195.0, 12600.0)
        total_km = sum(s.split_km for s in ps.splits)
        assert total_km == pytest.approx(42.195, abs=0.01)

    def test_conservative_start_first_split_slower(self):
        ps = build_pacing_strategy(42195.0, 12600.0)
        avg_pace = 12600.0 / (42195.0 / 1000.0)
        assert ps.splits[0].target_pace_sec_per_km > avg_pace

    def test_negative_split_last_segment_faster(self):
        ps = build_pacing_strategy(21097.5, 5400.0)
        avg_pace = 5400.0 / (21097.5 / 1000.0)
        assert ps.splits[-1].target_pace_sec_per_km < avg_pace

    def test_key_guidance_not_empty(self):
        for dist in [5000.0, 10000.0, 21097.5, 42195.0]:
            target = predict_time(50.0, dist)
            ps = build_pacing_strategy(dist, target)
            assert len(ps.key_guidance) >= 3

    def test_explicit_strategy_override(self):
        ps = build_pacing_strategy(42195.0, 12600.0, strategy="even_split")
        assert ps.strategy_name == "even_split"
        # Even splits should all have the same pace
        paces = [s.target_pace_sec_per_km for s in ps.splits]
        assert all(p == paces[0] for p in paces)

    def test_effort_notes_present(self):
        ps = build_pacing_strategy(5000.0, 1200.0)
        for s in ps.splits:
            assert len(s.effort_note) > 0


# ── TestAssessRaceReadiness ──────────────────────────────────────────────────


class TestAssessRaceReadiness:
    def test_fully_ready_athlete(self):
        profile = make_profile(vdot=55.0, ctl=50.0, tsb=10.0)
        goal = make_goal(distance_m=21097.5, target_time_s=5400.0)
        plan = make_plan(start_offset_days=-56, duration_weeks=8, completion=1.0)
        r = assess_race_readiness(profile, goal, plan)
        assert r.overall_score >= 0.75
        assert r.overall_status == "ready"

    def test_fatigued_athlete(self):
        profile = make_profile(tsb=-20.0)
        goal = make_goal()
        r = assess_race_readiness(profile, goal)
        tsb_comp = next(c for c in r.components if c.name == "TSB Form")
        assert tsb_comp.score <= 0.3
        assert tsb_comp.status == "not_ready"

    def test_no_training_plan(self):
        profile = make_profile()
        goal = make_goal()
        r = assess_race_readiness(profile, goal, plan=None)
        comp = next(c for c in r.components if c.name == "Training Completion")
        assert comp.score == 0.5

    def test_ambitious_target(self):
        # VDOT 40 trying to run a fast half
        profile = make_profile(vdot=40.0)
        goal = make_goal(distance_m=21097.5, target_time_s=4800.0)  # 1:20:00
        r = assess_race_readiness(profile, goal)
        vdot_comp = next(c for c in r.components if c.name == "VDOT Fitness")
        assert vdot_comp.score <= 0.4

    def test_no_target_time(self):
        profile = make_profile(vdot=50.0)
        goal = make_goal(target_time_s=None)
        r = assess_race_readiness(profile, goal)
        vdot_comp = next(c for c in r.components if c.name == "VDOT Fitness")
        assert vdot_comp.score == 0.8

    def test_no_vdot(self):
        profile = make_profile(vdot=None)
        goal = make_goal()
        r = assess_race_readiness(profile, goal)
        vdot_comp = next(c for c in r.components if c.name == "VDOT Fitness")
        assert vdot_comp.score == 0.3

    def test_low_ctl_for_marathon(self):
        profile = make_profile(ctl=30.0)
        goal = make_goal(distance_m=42195.0)
        r = assess_race_readiness(profile, goal)
        ctl_comp = next(c for c in r.components if c.name == "CTL Fitness")
        assert ctl_comp.status == "not_ready"

    def test_adequate_ctl_for_5k(self):
        profile = make_profile(ctl=30.0)
        goal = make_goal(distance_m=5000.0)
        r = assess_race_readiness(profile, goal)
        ctl_comp = next(c for c in r.components if c.name == "CTL Fitness")
        assert ctl_comp.status == "ready"

    def test_long_run_insufficient_for_marathon(self):
        profile = make_profile(long_run_avg=20.0)
        goal = make_goal(distance_m=42195.0)
        r = assess_race_readiness(profile, goal)
        lr = next(c for c in r.components if c.name == "Long Run Readiness")
        assert lr.status == "not_ready"

    def test_long_run_irrelevant_for_5k(self):
        profile = make_profile(long_run_avg=8.0)
        goal = make_goal(distance_m=5000.0)
        r = assess_race_readiness(profile, goal)
        lr = next(c for c in r.components if c.name == "Long Run Readiness")
        assert lr.score == 0.9

    def test_score_is_weighted_sum(self):
        profile = make_profile()
        goal = make_goal()
        r = assess_race_readiness(profile, goal)
        weights = {
            "VDOT Fitness": 0.30,
            "CTL Fitness": 0.25,
            "TSB Form": 0.20,
            "Training Completion": 0.15,
            "Long Run Readiness": 0.10,
        }
        expected = sum(c.score * weights[c.name] for c in r.components)
        assert r.overall_score == pytest.approx(expected, abs=0.001)

    def test_recommendations_for_weak_components(self):
        profile = make_profile(vdot=40.0, ctl=20.0, tsb=-15.0)
        goal = make_goal(distance_m=42195.0, target_time_s=12000.0)
        r = assess_race_readiness(profile, goal)
        assert len(r.recommendations) > 0

    def test_no_recommendations_when_fully_ready(self):
        profile = make_profile(vdot=55.0, ctl=60.0, tsb=10.0, long_run_avg=32.0)
        goal = make_goal(distance_m=21097.5, target_time_s=6000.0)
        plan = make_plan(start_offset_days=-56, duration_weeks=8, completion=1.0)
        r = assess_race_readiness(profile, goal, plan)
        # All components should be >= 0.7, so no recommendations
        assert len(r.recommendations) == 0

    def test_days_to_race_calculated(self):
        race_date = date.today() + timedelta(days=14)
        profile = make_profile()
        goal = make_goal(race_date=race_date)
        r = assess_race_readiness(profile, goal)
        assert r.days_to_race == 14

    def test_no_race_date(self):
        profile = make_profile()
        goal = make_goal()
        goal.race_date = None
        r = assess_race_readiness(profile, goal)
        assert r.days_to_race is None

    def test_overall_status_thresholds(self):
        # Ready: >= 0.75
        profile = make_profile(vdot=55.0, ctl=60.0, tsb=10.0, long_run_avg=20.0)
        goal = make_goal(distance_m=21097.5, target_time_s=6000.0)
        plan = make_plan(start_offset_days=-56, duration_weeks=8, completion=1.0)
        r = assess_race_readiness(profile, goal, plan)
        assert r.overall_status == "ready"

        # Not ready: < 0.50
        profile2 = make_profile(vdot=None, ctl=None, tsb=-20.0, long_run_avg=5.0)
        goal2 = make_goal(distance_m=42195.0, target_time_s=10000.0)
        r2 = assess_race_readiness(profile2, goal2)
        assert r2.overall_status == "not_ready"


# ── TestEndurancePenalty ─────────────────────────────────────────────────────


class TestEndurancePenalty:
    @staticmethod
    def _time(label: str, ctl: float | None) -> float:
        preds = predict_race_times(50.0, ctl=ctl)
        return next(p for p in preds if p.distance_label == label).predicted_time_s

    def test_low_ctl_slows_marathon(self):
        assert self._time("Marathon", 30.0) > self._time("Marathon", 60.0)

    def test_adequate_ctl_means_no_penalty(self):
        # CTL >= 50 → multiplier 1.0, identical to no-CTL baseline
        assert self._time("Marathon", 60.0) == pytest.approx(self._time("Marathon", None))

    def test_short_races_unaffected_by_ctl(self):
        for label in ("5K", "10K"):
            assert self._time(label, 20.0) == pytest.approx(self._time(label, None))

    def test_penalty_capped_at_6_percent(self):
        baseline = self._time("Marathon", None)
        assert self._time("Marathon", 0.0) == pytest.approx(baseline * 1.06)

    def test_half_penalized_less_than_marathon(self):
        half_ratio = self._time("Half Marathon", 30.0) / self._time("Half Marathon", None)
        full_ratio = self._time("Marathon", 30.0) / self._time("Marathon", None)
        assert 1.0 < half_ratio < full_ratio
