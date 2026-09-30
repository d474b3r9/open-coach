"""Per-day duration caps, injury check-in after a session, adjusting one planned session."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from open_coach.models import (
    InjuryRecord,
    TrainingConstraints,
    TrainingPlan,
    TrainingWeek,
)
from open_coach.periodization import DAY_INDEX, max_minutes_for_day
from open_coach.sports.running import pace
from open_coach.sports.running.plan import SHORT_DAY_MINUTES, generate_plan
from open_coach.storage import CoachStorage
from open_coach.tools.memory import record_workout_feedback, set_training_constraints
from open_coach.tools.plans import adjust_planned_workout, update_workout_completion
from tests.conftest import make_goal, make_planned_workout, mock_ctx

MONDAY = DAY_INDEX["monday"]


def _monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


# ── Per-day caps ──────────────────────────────────────────────────────────────


def test_per_day_cap_wins_over_the_weekday_cap() -> None:
    constraints = TrainingConstraints(max_weekday_minutes=90, max_minutes_by_day={"Monday": 45})

    assert constraints.max_minutes_by_day == {"monday": 45}
    assert max_minutes_for_day(MONDAY, constraints) == 45
    assert max_minutes_for_day(DAY_INDEX["tuesday"], constraints) == 90
    assert max_minutes_for_day(DAY_INDEX["sunday"], constraints) is None


def test_unknown_weekday_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown weekday"):
        TrainingConstraints(max_minutes_by_day={"lundi": 45})


def test_short_monday_only_gets_easy_runs_within_its_cap() -> None:
    constraints = TrainingConstraints(
        available_days=["monday", "wednesday", "friday", "sunday"],
        max_minutes_by_day={"monday": 45},
    )
    plan = generate_plan(make_goal(42195, weeks_ahead=16), 50.0, 45.0, constraints, _monday())

    mondays = [w for week in plan.weeks for w in week.workouts if w.date.weekday() == MONDAY]
    assert mondays
    assert SHORT_DAY_MINUTES > 45
    for w in mondays:
        assert w.workout_type in {"easy", "recovery", "race"}
        if w.workout_type != "race":
            assert w.target_duration_s is not None
            assert w.target_duration_s <= 45 * 60
    # The long run and the quality sessions still exist, on other days.
    others = {w.workout_type for week in plan.weeks for w in week.workouts}
    assert {"long_run", "tempo", "intervals"} <= others


async def test_set_training_constraints_stores_per_day_caps(storage: CoachStorage) -> None:
    ctx = mock_ctx(storage=storage)

    ok = await set_training_constraints(max_minutes_by_day={"monday": 45}, ctx=ctx)
    bad = await set_training_constraints(max_minutes_by_day={"funday": 45}, ctx=ctx)

    assert ok == {"status": "constraints_updated"}
    assert "Unknown weekday" in bad["error"]
    saved = storage.load_constraints()
    assert saved is not None
    assert saved.max_minutes_by_day == {"monday": 45}


# ── Injury check-in ───────────────────────────────────────────────────────────


def _plan_with(*workouts) -> TrainingPlan:
    start = min(w.date for w in workouts) - timedelta(days=1)
    return TrainingPlan(
        name="Test plan",
        goal=make_goal(10000, weeks_ahead=6),
        start_date=start,
        end_date=start + timedelta(weeks=6),
        weeks=[TrainingWeek(week_number=1, start_date=start, workouts=list(workouts))],
    )


def _injured(storage: CoachStorage, resolved: bool = False) -> None:
    storage.save_constraints(
        TrainingConstraints(
            injuries=[
                InjuryRecord(
                    description="plantar fascia",
                    body_part="right foot",
                    severity="moderate",
                    date_reported=date.today() - timedelta(days=5),
                    resolved=resolved,
                )
            ]
        )
    )


async def test_completion_asks_for_an_injury_check_in(storage: CoachStorage) -> None:
    workout = make_planned_workout(offset_days=0)
    storage.save_plan(_plan_with(workout))
    _injured(storage)

    result = await update_workout_completion(
        week_number=1, workout_date=workout.date.isoformat(), ctx=mock_ctx(storage=storage)
    )

    assert [i["body_part"] for i in result["active_injuries"]] == ["right foot"]
    assert "Injury check-in" in result["next_steps"][0]


async def test_feedback_asks_for_an_injury_check_in(storage: CoachStorage) -> None:
    _injured(storage)

    result = await record_workout_feedback(workout_type="easy", ctx=mock_ctx(storage=storage))

    assert result["active_injuries"][0]["severity"] == "moderate"
    assert "resolve_injury" in result["next_steps"][0]


async def test_no_check_in_once_the_injury_is_resolved(storage: CoachStorage) -> None:
    workout = make_planned_workout(offset_days=0)
    storage.save_plan(_plan_with(workout))
    _injured(storage, resolved=True)

    result = await update_workout_completion(
        week_number=1, workout_date=workout.date.isoformat(), ctx=mock_ctx(storage=storage)
    )

    assert "active_injuries" not in result
    assert not any("Injury" in step for step in result["next_steps"])


# ── adjust_planned_workout ────────────────────────────────────────────────────


async def test_swap_to_easy_updates_the_plan_and_asks_for_a_watch_sync(
    storage: CoachStorage,
) -> None:
    tempo = make_planned_workout(offset_days=1, wtype="tempo", pace=265.0, dist=10.0)
    storage.save_plan(_plan_with(tempo))

    result = await adjust_planned_workout(
        workout_date=tempo.date.isoformat(),
        workout_type="easy",
        description="Easy run 8km @ 5:30/km",
        target_distance_m=8000,
        reason="recovery red: HRV -12%",
        ctx=mock_ctx(storage=storage),
    )

    assert result["status"] == "adjusted"
    assert result["before"]["type"] == "tempo"
    assert any("list_watch_workouts" in step for step in result["next_steps"])
    saved = storage.load_active_plan()
    assert saved is not None
    [w] = saved.weeks[0].workouts
    assert w.workout_type == "easy"
    assert w.target_intensity is None  # the tempo pace no longer applies
    assert w.target_distance_m == 8000
    assert w.adjustment_note == "recovery red: HRV -12%"


async def test_new_intensity_can_be_given_with_the_swap(storage: CoachStorage) -> None:
    tempo = make_planned_workout(offset_days=1, wtype="tempo", pace=265.0)
    storage.save_plan(_plan_with(tempo))

    await adjust_planned_workout(
        workout_date=tempo.date.isoformat(),
        workout_type="easy",
        target_intensity=pace(330.0),
        ctx=mock_ctx(storage=storage),
    )

    saved = storage.load_active_plan()
    assert saved is not None
    assert saved.weeks[0].workouts[0].target_intensity == pace(330.0)


async def test_rest_day_drops_the_targets(storage: CoachStorage) -> None:
    tempo = make_planned_workout(offset_days=1, wtype="tempo", pace=265.0, dist=10.0)
    storage.save_plan(_plan_with(tempo))

    await adjust_planned_workout(
        workout_date=tempo.date.isoformat(), workout_type="rest", ctx=mock_ctx(storage=storage)
    )

    saved = storage.load_active_plan()
    assert saved is not None
    w = saved.weeks[0].workouts[0]
    assert w.workout_type == "rest"
    assert w.target_distance_m is None
    assert w.target_intensity is None


async def test_adjust_refuses_completed_or_missing_sessions(storage: CoachStorage) -> None:
    done = make_planned_workout(offset_days=-1, completed=True)
    storage.save_plan(_plan_with(done))
    ctx = mock_ctx(storage=storage)

    completed = await adjust_planned_workout(workout_date=done.date.isoformat(), ctx=ctx)
    missing = await adjust_planned_workout(workout_date="2030-01-01", ctx=ctx)
    bad_date = await adjust_planned_workout(workout_date="tomorrow", ctx=ctx)

    assert "already completed" in completed["error"]
    assert "No planned session" in missing["error"]
    assert "error" in bad_date
