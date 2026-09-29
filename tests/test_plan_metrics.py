"""Tests for open_coach.plan_metrics — pure week-actuals recomputation."""

from __future__ import annotations

from datetime import date

from open_coach.models import ExtraActivity, PlannedWorkout, TrainingWeek
from open_coach.plan_metrics import NON_RUN_TYPES, is_run_workout, recompute_week_actuals


def _w(wtype: str, completed: bool = False, km: float | None = None) -> PlannedWorkout:
    return PlannedWorkout(
        date=date(2026, 7, 6),
        workout_type=wtype,
        description=wtype,
        completed=completed,
        actual_distance_km=km,
    )


def _week(*workouts: PlannedWorkout, extras: list[ExtraActivity] | None = None) -> TrainingWeek:
    return TrainingWeek(
        week_number=1,
        start_date=date(2026, 7, 6),
        workouts=list(workouts),
        extra_activities=extras or [],
    )


def test_is_run_workout_excludes_rest_and_strength() -> None:
    assert is_run_workout(_w("easy"))
    assert not is_run_workout(_w("strength"))
    assert not is_run_workout(_w("kiné-renfo"))  # legacy French name
    assert is_run_workout(_w("Interval"))
    for t in NON_RUN_TYPES:
        assert not is_run_workout(_w(t))
    assert not is_run_workout(_w("REST"))


def test_completion_rate_counts_only_run_sessions() -> None:
    week = _week(_w("easy", True, 8.0), _w("tempo", False), _w("rest"), _w("kiné-renfo"))
    recompute_week_actuals(week)
    assert week.completion_rate == 0.5


def test_completion_rate_zero_when_no_run_sessions() -> None:
    week = _week(_w("rest"), _w("rest"))
    recompute_week_actuals(week)
    assert week.completion_rate == 0.0


def test_volume_sums_completed_workouts_and_extras() -> None:
    extras = [ExtraActivity(date=date(2026, 7, 9), distance_km=5.25, name="Riverside Course")]
    week = _week(
        _w("easy", True, 8.0), _w("long_run", True, None), _w("tempo", False, 12.0), extras=extras
    )
    recompute_week_actuals(week)
    # completed without recorded distance counts 0, skipped workouts never count
    assert week.actual_volume_km == 13.25
