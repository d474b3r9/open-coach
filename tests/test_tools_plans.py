"""Tests for the training-plan MCP tools (tools/plans.py)."""

from __future__ import annotations

from datetime import date, timedelta
from functools import partial
from pathlib import Path

from open_coach.models import (
    AthleteProfile,
    GoalsConfig,
    InjuryRecord,
    PlannedWorkout,
    TrainingConstraints,
    TrainingGoal,
)
from open_coach.sports.running.plan_to_dsl import convert_planned_workout
from open_coach.tools.plans import (
    _next_monday,
    generate_training_plan,
    sync_upcoming_workouts,
    update_workout_completion,
)
from open_coach.workout_dsl import DSLWorkout, RepeatBlock
from tests.conftest import StubGarmin, make_plan, make_planned_workout, mock_ctx, running_profile

# ── Helpers ──────────────────────────────────────────────────────────────────

# Canonical factory lives in conftest; this module's workouts default to
# tomorrow with an easy pace so they land inside the sync window.
_workout = partial(make_planned_workout, offset_days=1, pace=330.0)


def _planned_workout_to_dsl(workout: PlannedWorkout) -> DSLWorkout | None:
    """The DSL the running plugin builds from a plan session (None when refused)."""
    return convert_planned_workout(workout).dsl


def _plan_with_workouts(workouts):
    plan = make_plan(start_offset_days=-7, duration_weeks=4)
    plan.weeks[0].workouts = list(workouts)
    return plan


def _seed_profile_and_goal(storage, race_offset_weeks=12):
    storage.save_profile(running_profile(vdot=48.0, ctl=40.0, onboarding_complete=True))
    goal = TrainingGoal(
        sport="running",
        race_name="Autumn 10K",
        distance_m=10000,
        race_date=date.today() + timedelta(weeks=race_offset_weeks),
    )
    storage.save_goals(GoalsConfig(goals=[goal]))


# ── _next_monday ─────────────────────────────────────────────────────────────


class TestNextMonday:
    def test_monday_maps_to_itself(self):
        monday = date(2026, 7, 6)
        assert _next_monday(monday) == monday

    def test_midweek_maps_to_next_monday(self):
        assert _next_monday(date(2026, 7, 8)) == date(2026, 7, 13)  # Wednesday

    def test_sunday_maps_to_next_day(self):
        assert _next_monday(date(2026, 7, 12)) == date(2026, 7, 13)


# ── _planned_workout_to_dsl ──────────────────────────────────────────────────


class TestPlannedWorkoutToDsl:
    """Thin wrapper over plan_to_dsl.convert_planned_workout — full grammar
    coverage lives in tests/test_plan_to_dsl.py."""

    def test_easy_run_is_a_single_block(self):
        dsl = _planned_workout_to_dsl(_workout(wtype="easy", pace=330.0, dist=10.0))
        assert dsl is not None
        assert len(dsl.steps) == 1  # Rule A — builder appends the lap finish
        assert dsl.name == "easy run"

    def test_easy_without_pace_returns_none(self):
        assert _planned_workout_to_dsl(_workout(wtype="easy", pace=None)) is None

    def test_tempo_without_structure_is_not_guessed(self):
        # Old heuristic built "total - 3.5 km at pace"; now refused.
        assert _planned_workout_to_dsl(_workout(wtype="tempo", pace=270.0, dist=10.0)) is None

    def test_intervals_parses_rep_count_from_description(self):
        w = _workout(wtype="intervals", pace=240.0, description="6x1000m @ interval pace")
        dsl = _planned_workout_to_dsl(w)
        assert dsl is not None
        repeat = next(s for s in dsl.steps if isinstance(s, RepeatBlock))
        assert repeat.count == 6

    def test_intervals_without_sets_returns_none(self):
        w = _workout(wtype="intervals", pace=240.0, description="VMA session")
        assert _planned_workout_to_dsl(w) is None

    def test_unknown_type_returns_none(self):
        assert _planned_workout_to_dsl(_workout(wtype="rest", pace=None)) is None
        assert _planned_workout_to_dsl(_workout(wtype="cross_training")) is None


# ── generate_training_plan ───────────────────────────────────────────────────


class TestGenerateTrainingPlan:
    async def test_no_profile_returns_error(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await generate_training_plan(ctx=ctx)
        assert "error" in result

    async def test_profile_without_vdot_returns_error(self, storage):
        storage.save_profile(AthleteProfile())
        ctx = mock_ctx(storage=storage)
        result = await generate_training_plan(ctx=ctx)
        assert "error" in result

    async def test_no_goals_returns_error(self, storage):
        storage.save_profile(running_profile(vdot=48.0))
        ctx = mock_ctx(storage=storage)
        result = await generate_training_plan(ctx=ctx)
        assert "error" in result

    async def test_goal_index_out_of_range(self, storage):
        _seed_profile_and_goal(storage)
        ctx = mock_ctx(storage=storage)
        result = await generate_training_plan(goal_index=5, ctx=ctx)
        assert "error" in result

    async def test_goal_without_race_date_returns_error(self, storage):
        storage.save_profile(running_profile(vdot=48.0))
        storage.save_goals(GoalsConfig(goals=[TrainingGoal(sport="running", distance_m=10000)]))
        ctx = mock_ctx(storage=storage)
        result = await generate_training_plan(ctx=ctx)
        assert "error" in result

    async def test_race_before_start_returns_error(self, storage):
        _seed_profile_and_goal(storage, race_offset_weeks=12)
        ctx = mock_ctx(storage=storage)
        start = (date.today() + timedelta(weeks=20)).isoformat()
        result = await generate_training_plan(start_date=start, ctx=ctx)
        assert "error" in result

    async def test_happy_path_saves_plan_and_markdown(self, storage, tmp_path):
        _seed_profile_and_goal(storage, race_offset_weeks=12)
        ctx = mock_ctx(storage=storage)
        result = await generate_training_plan(ctx=ctx)

        assert result["status"] == "plan_generated"
        assert result["weeks"] > 0
        assert result["start_volume"].endswith(" km")
        assert result["peak_volume"].endswith(" km")
        start_km = float(result["start_volume"].removesuffix(" km"))
        peak_km = float(result["peak_volume"].removesuffix(" km"))
        assert peak_km >= start_km > 0
        assert result["phases"]  # at least one phase bucket

        saved = storage.load_active_plan()
        assert saved is not None
        assert saved.name == result["name"]
        volumes = [w.planned_volume["running"].distance_m for w in saved.weeks]
        assert max(volumes) >= volumes[0] > 0

        # Markdown copy lands in the env-overridden tmp dir (see conftest)
        assert result["markdown_copy"] is not None
        assert str(tmp_path) in result["markdown_copy"]

    async def test_regenerating_for_another_goal_removes_stale_markdown(self, storage):
        # Regression: the auto-archived plan's markdown copy stayed in plans/.
        _seed_profile_and_goal(storage, race_offset_weeks=12)
        goals = storage.load_goals()
        goals.goals.append(
            TrainingGoal(
                sport="running",
                race_name="Spring 5K",
                distance_m=5000,
                race_date=date.today() + timedelta(weeks=6),
            )
        )
        storage.save_goals(goals)
        first = await generate_training_plan(goal_index=0, ctx=mock_ctx(storage=storage))
        second = await generate_training_plan(goal_index=1, ctx=mock_ctx(storage=storage))

        assert second["auto_archived"] == first["name"]
        assert not Path(first["markdown_copy"]).exists()
        assert Path(second["markdown_copy"]).exists()

    async def test_profile_language_drives_plan_and_markdown(self, storage):
        _seed_profile_and_goal(storage, race_offset_weeks=12)
        profile = storage.load_profile()
        profile.language = "fr"
        storage.save_profile(profile)
        result = await generate_training_plan(ctx=mock_ctx(storage=storage))

        assert "semaines" in result["name"]
        md = Path(result["markdown_copy"]).read_text(encoding="utf-8")
        assert "## Course cible" in md

    async def test_no_constraints_means_no_warnings_keys(self, storage):
        _seed_profile_and_goal(storage)
        result = await generate_training_plan(ctx=mock_ctx(storage=storage))
        assert result["status"] == "plan_generated"
        assert "warnings" not in result
        assert "constraints_notes" not in result

    async def test_active_injuries_surface_as_warnings(self, storage):
        _seed_profile_and_goal(storage)
        storage.save_constraints(
            TrainingConstraints(
                injuries=[
                    InjuryRecord(
                        description="Achilles pain",
                        body_part="achilles",
                        severity="moderate",
                        date_reported=date.today() - timedelta(days=10),
                    ),
                    InjuryRecord(
                        description="Old knee issue",
                        body_part="knee",
                        date_reported=date.today() - timedelta(days=90),
                        resolved=True,
                        resolved_date=date.today() - timedelta(days=60),
                    ),
                ]
            )
        )
        result = await generate_training_plan(ctx=mock_ctx(storage=storage))
        assert result["status"] == "plan_generated"
        # Only the ACTIVE injury is surfaced — the resolved one is not
        assert len(result["warnings"]) == 1
        assert "achilles" in result["warnings"][0]
        assert "moderate" in result["warnings"][0]
        assert "constraints_notes" not in result

    async def test_constraints_notes_surface_in_response(self, storage):
        _seed_profile_and_goal(storage)
        storage.save_constraints(TrainingConstraints(notes="physio Tuesdays"))
        result = await generate_training_plan(ctx=mock_ctx(storage=storage))
        assert result["status"] == "plan_generated"
        assert result["constraints_notes"] == "physio Tuesdays"
        assert "warnings" not in result


# ── sync_upcoming_workouts ───────────────────────────────────────────────────


class TestSyncUpcomingWorkouts:
    async def test_no_garmin_returns_error(self, storage):
        ctx = mock_ctx(storage=storage, garmin=None)
        result = await sync_upcoming_workouts(ctx=ctx)
        assert "error" in result

    async def test_no_plan_returns_error(self, storage):
        ctx = mock_ctx(storage=storage, garmin=StubGarmin())
        result = await sync_upcoming_workouts(ctx=ctx)
        assert "error" in result

    async def test_nothing_to_sync(self, storage):
        # Only a completed workout in the window and one outside the window
        plan = _plan_with_workouts(
            [_workout(offset_days=1, completed=True), _workout(offset_days=60)]
        )
        storage.save_plan(plan)
        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await sync_upcoming_workouts(weeks_ahead=2, ctx=ctx)
        assert result["status"] == "nothing_to_sync"
        assert garmin.calls == []

    async def test_happy_path_uploads_and_schedules(self, storage):
        plan = _plan_with_workouts([_workout(offset_days=1)])
        storage.save_plan(plan)
        garmin = StubGarmin(
            upload_workout={"workoutId": 111},
            schedule_workout={"workoutScheduleId": 222},
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await sync_upcoming_workouts(include_easy=True, ctx=ctx)

        assert result["status"] == "complete"
        assert result["uploaded"] == 1
        assert result["errors"] == []

        registry = storage.load_workout_registry()
        entry = registry.find(111)
        assert entry is not None
        assert entry.schedule_ids == [222]
        assert entry.schedule_dates == [date.today() + timedelta(days=1)]

    async def test_easy_runs_are_not_pushed_by_default(self, storage):
        # Project rule: easy runs are run on feel, no watch workout for them.
        storage.save_profile(running_profile(vdot=48.7, onboarding_complete=True))
        easy = _workout(offset_days=1)
        plain_long = _workout(offset_days=2, wtype="long_run", dist=18.0)
        long_with_m = _workout(
            offset_days=3,
            wtype="long_run",
            pace=330.0,
            dist=22.0,
            description="LR 22 km including 6 km @ M 4:37",
        )
        storage.save_plan(_plan_with_workouts([easy, plain_long, long_with_m]))
        garmin = StubGarmin(
            upload_workout={"workoutId": 111},
            schedule_workout={"workoutScheduleId": 222},
        )
        result = await sync_upcoming_workouts(ctx=mock_ctx(storage=storage, garmin=garmin))
        assert result["uploaded"] == 1
        assert [u["date"] for u in result["left_unpushed"]] == [
            str(easy.date),
            str(plain_long.date),
        ]

    async def test_include_easy_pushes_easy_runs(self, storage):
        storage.save_plan(_plan_with_workouts([_workout(offset_days=1)]))
        garmin = StubGarmin(
            upload_workout={"workoutId": 111},
            schedule_workout={"workoutScheduleId": 222},
        )
        result = await sync_upcoming_workouts(
            include_easy=True, ctx=mock_ctx(storage=storage, garmin=garmin)
        )
        assert result["uploaded"] == 1
        assert "left_unpushed" not in result

    async def test_skips_dates_already_in_registry(self, storage):
        target = _workout(offset_days=1)
        storage.save_plan(_plan_with_workouts([target]))

        # Pre-register an upload already scheduled on the same date
        from datetime import datetime

        from open_coach.models import WorkoutUpload

        storage.register_workout_upload(
            WorkoutUpload(workout_id=99, name="prior", uploaded_at=datetime.now())
        )
        storage.record_workout_schedule(99, 990, target.date.isoformat())

        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await sync_upcoming_workouts(ctx=ctx)
        assert result["uploaded"] == 0
        assert result["skipped"] == 1
        assert garmin.calls == []

    async def test_workout_without_pace_is_skipped(self, storage):
        storage.save_plan(_plan_with_workouts([_workout(offset_days=1, pace=None)]))
        ctx = mock_ctx(storage=storage, garmin=StubGarmin())
        result = await sync_upcoming_workouts(include_easy=True, ctx=ctx)
        assert result["skipped"] == 1
        assert result["uploaded"] == 0
        assert result["not_converted"][0]["reason"]

    async def test_unparsable_quality_session_is_reported_not_guessed(self, storage):
        w = _workout(
            offset_days=1, wtype="tempo", pace=277.0, dist=10.0, description="Q2 M-pace libre"
        )
        storage.save_plan(_plan_with_workouts([w]))
        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await sync_upcoming_workouts(ctx=ctx)
        assert result["uploaded"] == 0
        assert garmin.calls == []
        (nc,) = result["not_converted"]
        assert nc["date"] == str(w.date)
        assert "structure" in nc["reason"]
        assert "build_and_push_workout" in result["hint"]

    async def test_zone_letter_resolved_from_profile_vdot(self, storage):
        storage.save_profile(running_profile(vdot=48.7, onboarding_complete=True))
        w = _workout(
            offset_days=1,
            wtype="tempo",
            pace=277.0,
            dist=12.0,
            description="Q2 M-pace : 12 km dont 30 min @ M",
        )
        storage.save_plan(_plan_with_workouts([w]))
        garmin = StubGarmin(
            upload_workout={"workoutId": 111},
            schedule_workout={"workoutScheduleId": 222},
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await sync_upcoming_workouts(ctx=ctx)
        assert result["uploaded"] == 1
        payload = next(c for c in garmin.calls if c[0] == "upload_workout")[1][0]
        steps = payload["workoutSegments"][0]["workoutSteps"]  # raw upload dict
        # lap warmup, 30-min M block, lap cooldown (+ auto lap finish dedup → none added)
        assert steps[0]["endCondition"]["conditionTypeKey"] == "lap.button"
        assert steps[-1]["endCondition"]["conditionTypeKey"] == "lap.button"
        block = steps[1]
        assert block["workoutSteps"][0]["endConditionValue"] == 1800

    async def test_rate_limit_stops_early(self, storage):
        plan = _plan_with_workouts([_workout(offset_days=1), _workout(offset_days=2)])
        storage.save_plan(plan)
        garmin = StubGarmin(upload_workout=RuntimeError("429 Too Many Requests"))
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await sync_upcoming_workouts(include_easy=True, ctx=ctx)
        assert result["status"] == "rate_limited"
        assert result["uploaded"] == 0
        assert result["errors"][0]["error"] == "rate_limited"
        # Stopped after the first failure — second workout not attempted
        assert len([c for c in garmin.calls if c[0] == "upload_workout"]) == 1

    async def test_generic_error_is_partial(self, storage):
        storage.save_plan(_plan_with_workouts([_workout(offset_days=1)]))
        garmin = StubGarmin(upload_workout=RuntimeError("server exploded"))
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await sync_upcoming_workouts(include_easy=True, ctx=ctx)
        assert result["status"] == "partial"
        assert result["errors"][0]["error"] == "server exploded"


# ── update_workout_completion ────────────────────────────────────────────────


class TestUpdateWorkoutCompletion:
    async def test_no_plan_returns_error(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await update_workout_completion(1, "2026-07-10", ctx=ctx)
        assert "error" in result

    async def test_missing_week_returns_error(self, storage):
        storage.save_plan(_plan_with_workouts([_workout()]))
        ctx = mock_ctx(storage=storage)
        result = await update_workout_completion(42, "2026-07-10", ctx=ctx)
        assert "error" in result

    async def test_missing_workout_returns_error(self, storage):
        storage.save_plan(_plan_with_workouts([_workout(offset_days=1)]))
        ctx = mock_ctx(storage=storage)
        result = await update_workout_completion(1, "1999-01-01", ctx=ctx)
        assert "error" in result

    async def test_malformed_date_returns_error(self, storage):
        storage.save_plan(_plan_with_workouts([_workout()]))
        ctx = mock_ctx(storage=storage)
        result = await update_workout_completion(1, "10/07/2026", ctx=ctx)
        assert "error" in result
        assert "workout_date" in result["error"]

    async def test_completion_rate_ignores_rest_days(self, storage):
        run = _workout(offset_days=0)
        rest = _workout(offset_days=1, wtype="rest", pace=None, dist=None)
        storage.save_plan(_plan_with_workouts([run, rest]))
        ctx = mock_ctx(storage=storage)
        result = await update_workout_completion(
            week_number=1, workout_date=run.date.isoformat(), actual_distance_m=8000.0, ctx=ctx
        )
        assert result["week_completion_rate"] == 1.0

    async def test_marks_completed_and_updates_rates(self, storage):
        w1 = _workout(offset_days=0)
        w2 = _workout(offset_days=2)
        storage.save_plan(_plan_with_workouts([w1, w2]))
        ctx = mock_ctx(storage=storage)

        result = await update_workout_completion(
            week_number=1,
            workout_date=w1.date.isoformat(),
            completed=True,
            activity_id=777,
            actual_distance_m=8400.0,
            ctx=ctx,
        )
        assert result["status"] == "updated"
        assert result["week_completion_rate"] == 0.5

        saved = storage.load_active_plan()
        week = saved.weeks[0]
        done = next(w for w in week.workouts if w.date == w1.date)
        assert done.completed is True
        assert done.actual_activity_id == 777
        assert done.actual_distance_m == 8400.0
        assert week.actual_volume["running"].distance_m == 8400.0

    async def test_marks_skipped_with_reason(self, storage):
        w = _workout(offset_days=0)
        storage.save_plan(_plan_with_workouts([w]))
        ctx = mock_ctx(storage=storage)
        result = await update_workout_completion(
            week_number=1,
            workout_date=w.date.isoformat(),
            completed=False,
            skipped_reason="sick",
            ctx=ctx,
        )
        assert result["completed"] is False
        saved = storage.load_active_plan()
        assert saved.weeks[0].workouts[0].skipped_reason == "sick"
        assert saved.weeks[0].completion_rate == 0.0
