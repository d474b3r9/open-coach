"""Tests for Pydantic data models — defaults, Literal validation, round-trips."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from open_coach.models import (
    ActivityCache,
    AdaptiveRecommendation,
    AthleteProfile,
    FeedbackLog,
    GoalsConfig,
    InjuryRecord,
    PersonalRecord,
    PlannedWorkout,
    RaceReadiness,
    RecoverySignal,
    SportProfile,
    TrainingConstraints,
    TrainingGoal,
    TrainingPlan,
    TrainingWeek,
    WorkoutFeedback,
    WorkoutRegistry,
    WorkoutUpload,
)
from open_coach.sports.base import FitnessMarker, Volume


def _pr(label="5K", **kwargs) -> PersonalRecord:
    defaults = {
        "distance_label": label,
        "distance_m": 5000.0,
        "time_s": 1500.0,
        "activity_id": 1,
        "date": date(2026, 5, 1),
    }
    defaults.update(kwargs)
    return PersonalRecord(**defaults)


# ── schema_version defaults ──────────────────────────────────────────────────


class TestSchemaVersionDefaults:
    @pytest.mark.parametrize(
        "model",
        [
            AthleteProfile(),
            GoalsConfig(),
            FeedbackLog(period="2026-Q3"),
            ActivityCache(),
        ],
    )
    def test_sport_agnostic_models_default_to_2(self, model):
        assert model.schema_version == 2

    @pytest.mark.parametrize("model", [TrainingConstraints(), WorkoutRegistry()])
    def test_defaults_to_1(self, model):
        assert model.schema_version == 1

    def test_training_plan_defaults_to_2(self):
        plan = TrainingPlan(
            name="p",
            goal=TrainingGoal(sport="running", distance_m=10000),
            start_date=date(2026, 1, 5),
            end_date=date(2026, 3, 1),
        )
        assert plan.schema_version == 2
        assert plan.status == "active"
        assert plan.weeks == []


# ── Literal field validation ─────────────────────────────────────────────────


class TestLiteralFields:
    def test_goal_priority_accepts_abc(self):
        for p in ("A", "B", "C"):
            assert TrainingGoal(sport="running", distance_m=5000, priority=p).priority == p

    def test_goal_priority_rejects_other(self):
        with pytest.raises(ValidationError):
            TrainingGoal(sport="running", distance_m=5000, priority="D")  # type: ignore[arg-type]

    def test_injury_severity_rejects_invalid(self):
        with pytest.raises(ValidationError):
            InjuryRecord(
                description="x",
                body_part="knee",
                severity="catastrophic",  # type: ignore[arg-type]
                date_reported=date.today(),
            )

    def test_injury_severity_default_minor(self):
        injury = InjuryRecord(description="x", body_part="knee", date_reported=date.today())
        assert injury.severity == "minor"
        assert injury.resolved is False

    def test_feedback_perceived_effort_rejects_invalid(self):
        with pytest.raises(ValidationError):
            WorkoutFeedback(date=date.today(), workout_type="easy", perceived_effort="impossible")  # type: ignore[arg-type]

    def test_feedback_feeling_rejects_invalid(self):
        with pytest.raises(ValidationError):
            WorkoutFeedback(date=date.today(), workout_type="easy", feeling="meh")  # type: ignore[arg-type]

    def test_plan_status_rejects_invalid(self):
        with pytest.raises(ValidationError):
            TrainingPlan(
                name="p",
                goal=TrainingGoal(sport="running", distance_m=10000),
                start_date=date(2026, 1, 5),
                end_date=date(2026, 3, 1),
                status="paused",  # type: ignore[arg-type]
            )

    def test_pr_source_literal(self):
        assert _pr().source == "detected"
        assert _pr(source="platform_pr").source == "platform_pr"
        assert _pr(source="garmin_pr").source == "platform_pr"  # legacy value
        with pytest.raises(ValidationError):
            _pr(source="strava")

    def test_adaptive_recommendation_action_literal(self):
        rec = AdaptiveRecommendation(action="rest_day", reasoning="red signals")
        assert rec.action == "rest_day"
        with pytest.raises(ValidationError):
            AdaptiveRecommendation(action="sprint_harder", reasoning="x")  # type: ignore[arg-type]

    def test_recovery_signal_status_literal(self):
        with pytest.raises(ValidationError):
            RecoverySignal(name="HRV", score=0.5, status="orange", value="v", detail="d")  # type: ignore[arg-type]

    def test_race_readiness_status_literal(self):
        with pytest.raises(ValidationError):
            RaceReadiness(
                overall_score=0.5,
                overall_status="maybe",  # type: ignore[arg-type]
                summary="s",
                components=[],
                recommendations=[],
            )

    def test_athlete_profile_rejects_non_positive_physiology(self):
        with pytest.raises(ValidationError):
            AthleteProfile(max_hr=0)
        with pytest.raises(ValidationError):
            AthleteProfile(resting_hr=-5)
        with pytest.raises(ValidationError):
            FitnessMarker(metric="vdot", value=-1.0)
        with pytest.raises(ValidationError):
            AthleteProfile(weight_kg=0)


# ── Default factories are independent instances ──────────────────────────────


class TestDefaultFactories:
    def test_profile_pr_lists_are_independent(self):
        a, b = AthleteProfile(), AthleteProfile()
        a.sport_profile("running", create=True).personal_records.append(_pr())
        assert b.sports == {}
        assert b.sport_profile("running").personal_records == []

    def test_week_workout_lists_are_independent(self):
        a = TrainingWeek(week_number=1, start_date=date(2026, 1, 5))
        b = TrainingWeek(week_number=2, start_date=date(2026, 1, 12))
        a.workouts.append(
            PlannedWorkout(date=date(2026, 1, 5), workout_type="easy", description="e")
        )
        assert b.workouts == []


# ── WorkoutRegistry helpers ──────────────────────────────────────────────────


class TestWorkoutRegistry:
    def _registry(self) -> WorkoutRegistry:
        return WorkoutRegistry(
            workouts=[
                WorkoutUpload(workout_id=1, name="a", uploaded_at=datetime(2026, 1, 1)),
                WorkoutUpload(
                    workout_id=2, name="b", uploaded_at=datetime(2026, 1, 2), deleted=True
                ),
            ]
        )

    def test_find_existing(self):
        found = self._registry().find(2)
        assert found is not None
        assert found.name == "b"

    def test_find_missing_returns_none(self):
        assert self._registry().find(99) is None

    def test_active_workouts_excludes_deleted(self):
        active = self._registry().active_workouts()
        assert [w.workout_id for w in active] == [1]


# ── Round-trip serialization ─────────────────────────────────────────────────


class TestRoundTrip:
    def test_training_plan_json_round_trip(self):
        plan = TrainingPlan(
            name="Marathon",
            goal=TrainingGoal(
                sport="running", distance_m=42195, race_date=date(2026, 10, 4), priority="A"
            ),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 10, 4),
            weeks=[
                TrainingWeek(
                    week_number=1,
                    start_date=date(2026, 6, 1),
                    planned_volume={"running": Volume(distance_m=40000.0)},
                    workouts=[
                        PlannedWorkout(
                            date=date(2026, 6, 2),
                            workout_type="easy",
                            description="Easy 8k",
                            target_distance_m=8000.0,
                        )
                    ],
                )
            ],
            created_at=datetime(2026, 5, 20, 12, 0),
        )
        restored = TrainingPlan.model_validate_json(plan.model_dump_json())
        assert restored == plan

    def test_athlete_profile_json_round_trip(self):
        profile = AthleteProfile(
            max_hr=190,
            resting_hr=48,
            sports={
                "running": SportProfile(
                    fitness=FitnessMarker(
                        metric="vdot", value=48.2, source="10K 42:00 on 2026-05-01"
                    ),
                    personal_records=[_pr()],
                )
            },
            ctl=45.0,
            atl=50.0,
            tsb=-5.0,
            onboarding_complete=True,
        )
        restored = AthleteProfile.model_validate_json(profile.model_dump_json())
        assert restored == profile

    def test_planned_workout_defaults(self):
        w = PlannedWorkout(date=date(2026, 6, 2), workout_type="tempo", description="t")
        assert w.completed is False
        assert w.actual_activity_id is None
        assert w.skipped_reason is None
