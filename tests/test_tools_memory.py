"""Tests for the persistent-memory MCP tools (tools/memory.py)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from open_coach.models import WorkoutRegistry, WorkoutUpload
from open_coach.plan_renderer import plan_markdown_path, write_plan_markdown
from open_coach.sports.running import vdot_of
from open_coach.tools.memory import (
    archive_active_plan,
    bootstrap_athlete_profile,
    record_workout_feedback,
    rename_active_plan,
    report_injury,
    resolve_injury,
    save_training_plan,
    set_training_constraints,
    set_training_goal,
    update_athlete_profile,
)
from tests.conftest import StubGarmin, make_plan, make_planned_workout, mock_ctx, running_profile

# ── bootstrap_athlete_profile ────────────────────────────────────────────────


class TestBootstrapAthleteProfile:
    async def test_no_garmin_returns_error(self, storage):
        ctx = mock_ctx(storage=storage, garmin=None)
        result = await bootstrap_athlete_profile(ctx=ctx)
        assert "error" in result

    async def test_already_complete_short_circuits(self, storage):
        storage.save_profile(running_profile(vdot=50.0, onboarding_complete=True))
        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await bootstrap_athlete_profile(ctx=ctx)
        assert result["status"] == "already_complete"
        assert result["vdot"] == 50.0
        assert garmin.calls == []  # no network activity

    async def test_happy_path_builds_profile(self, storage):
        run_date = (date.today() - timedelta(days=10)).isoformat()
        garmin = StubGarmin(
            get_activities_by_date=[
                {
                    "activityId": 101,
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": f"{run_date} 08:00:00",
                    "distance": 5000.0,
                    "duration": 1500.0,
                    "averageHR": 165.4,
                    "maxHR": 182.0,
                    "activityName": "Morning 5K",
                },
                {  # zero-distance run must be skipped
                    "activityId": 102,
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": f"{run_date} 18:00:00",
                    "distance": 0,
                    "duration": 600,
                },
                {  # distance-less session of another sport still loads
                    "activityId": 103,
                    "activityType": {"typeKey": "strength_training"},
                    "startTimeLocal": f"{run_date} 19:00:00",
                    "distance": 0,
                    "duration": 1800,
                    "averageHR": 110.0,
                },
            ],
            get_heart_rates={"restingHeartRate": 47},
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await bootstrap_athlete_profile(ctx=ctx)

        assert result["status"] == "complete"
        assert result["activities_scanned"] == 2  # the run + the strength session
        assert result["vdot"] is not None
        assert 30 < result["vdot"] < 45  # a 25:00 5K sits around VDOT 38
        assert result["resting_hr"] == 47

        profile = storage.load_profile()
        assert profile is not None
        assert profile.onboarding_complete is True
        assert [a.sport for a in storage.load_activity_cache()] == ["running", "other"]

    async def test_resting_hr_fetch_failure_falls_back(self, storage):
        run_date = (date.today() - timedelta(days=5)).isoformat()
        garmin = StubGarmin(
            get_activities_by_date=[
                {
                    "activityId": 1,
                    "startTimeLocal": f"{run_date} 08:00:00",
                    "distance": 10000.0,
                    "duration": 3000.0,
                    "averageHR": 150,
                }
            ],
            get_heart_rates=RuntimeError("boom"),
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await bootstrap_athlete_profile(ctx=ctx)
        assert result["status"] == "complete"  # soft-fail on HR fetch


# ── update_athlete_profile ───────────────────────────────────────────────────


class TestUpdateAthleteProfile:
    async def test_creates_profile_when_missing(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await update_athlete_profile(max_hr=192, resting_hr=46, ctx=ctx)
        assert result["status"] == "updated"
        profile = storage.load_profile()
        assert profile.max_hr == 192
        assert profile.resting_hr == 46

    async def test_only_provided_fields_change(self, storage):
        storage.save_profile(running_profile(vdot=48.0, max_hr=190))
        ctx = mock_ctx(storage=storage)
        await update_athlete_profile(weight_kg=71.5, ctx=ctx)
        profile = storage.load_profile()
        assert profile.weight_kg == 71.5
        assert profile.max_hr == 190
        assert vdot_of(profile) == 48.0

    async def test_fitness_override_sets_source(self, storage):
        ctx = mock_ctx(storage=storage)
        await update_athlete_profile(fitness_override=52.3, sport="running", ctx=ctx)
        profile = storage.load_profile()
        assert vdot_of(profile) == 52.3
        fitness = profile.sport_profile("running").fitness
        assert fitness is not None
        assert fitness.source == "manual override"

    async def test_language_defaults_to_en_and_can_be_set(self, storage):
        ctx = mock_ctx(storage=storage)
        await update_athlete_profile(max_hr=190, ctx=ctx)
        assert storage.load_profile().language == "en"
        await update_athlete_profile(language="fr", ctx=ctx)
        assert storage.load_profile().language == "fr"

    async def test_legacy_profile_without_language_loads(self, storage):
        (storage.base_dir / "profile.json").write_text('{"schema_version": 1, "vdot": 50.0}')
        assert storage.load_profile().language == "en"


# ── set_training_goal ────────────────────────────────────────────────────────


class TestSetTrainingGoal:
    async def test_adds_goal(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await set_training_goal(
            race_name="City 10K",
            distance_m=10000,
            race_date="2026-10-11",
            target_time_s=2400.0,
            priority="B",
            ctx=ctx,
        )
        assert result == {"status": "goal_added", "goals_count": 1}
        goals = storage.load_goals()
        goal = goals.goals[0]
        assert goal.race_name == "City 10K"
        assert goal.race_date == date(2026, 10, 11)
        assert goal.priority == "B"

    async def test_appends_to_existing_goals(self, storage):
        ctx = mock_ctx(storage=storage)
        await set_training_goal(race_name="A", distance_m=5000, ctx=ctx)
        result = await set_training_goal(race_name="B", distance_m=21097.5, ctx=ctx)
        assert result["goals_count"] == 2

    async def test_malformed_race_date_returns_error(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await set_training_goal(
            race_name="City 10K", distance_m=10000, race_date="11/10/2026", ctx=ctx
        )
        assert "error" in result
        assert "race_date" in result["error"]
        assert storage.load_goals() is None

    async def test_no_race_date_is_allowed(self, storage):
        ctx = mock_ctx(storage=storage)
        await set_training_goal(race_name="Someday", distance_m=42195, ctx=ctx)
        assert storage.load_goals().goals[0].race_date is None


# ── set_training_constraints ─────────────────────────────────────────────────


class TestSetTrainingConstraints:
    async def test_sets_fields(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await set_training_constraints(
            available_days=["monday", "thursday", "saturday"],
            max_sessions_per_week=4,
            ctx=ctx,
        )
        assert result == {"status": "constraints_updated"}
        constraints = storage.load_constraints()
        assert constraints.available_days == ["monday", "thursday", "saturday"]
        assert constraints.max_sessions_per_week == 4

    async def test_partial_update_preserves_existing(self, storage):
        ctx = mock_ctx(storage=storage)
        await set_training_constraints(available_days=["sunday"], ctx=ctx)
        await set_training_constraints(max_weekday_minutes=60, ctx=ctx)
        constraints = storage.load_constraints()
        assert constraints.available_days == ["sunday"]
        assert constraints.max_weekday_minutes == 60

    async def test_notes_persist(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await set_training_constraints(notes="physio Tuesdays", ctx=ctx)
        assert result == {"status": "constraints_updated"}
        constraints = storage.load_constraints()
        assert constraints is not None
        assert constraints.notes == "physio Tuesdays"


# ── report_injury ────────────────────────────────────────────────────────────


class TestReportInjury:
    async def test_records_injury(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await report_injury(
            description="Achilles pain after intervals",
            body_part="achilles",
            severity="moderate",
            ctx=ctx,
        )
        assert result == {"status": "injury_recorded", "total_injuries": 1}
        injury = storage.load_constraints().injuries[0]
        assert injury.body_part == "achilles"
        assert injury.severity == "moderate"
        assert injury.date_reported == date.today()
        assert injury.resolved is False

    async def test_appends_to_existing_injuries(self, storage):
        ctx = mock_ctx(storage=storage)
        await report_injury(description="a", body_part="knee", ctx=ctx)
        result = await report_injury(description="b", body_part="hip", ctx=ctx)
        assert result["total_injuries"] == 2


# ── resolve_injury ───────────────────────────────────────────────────────────


class TestResolveInjury:
    async def test_resolves_matching_unresolved_injuries(self, storage):
        ctx = mock_ctx(storage=storage)
        await report_injury(description="a", body_part="knee", ctx=ctx)
        await report_injury(description="b", body_part="knee", ctx=ctx)
        await report_injury(description="c", body_part="hip", ctx=ctx)

        result = await resolve_injury(body_part="knee", ctx=ctx)

        assert result == {"status": "injury_resolved", "resolved_count": 2}
        constraints = storage.load_constraints()
        assert constraints is not None
        knee, hip = (
            [i for i in constraints.injuries if i.body_part == "knee"],
            [i for i in constraints.injuries if i.body_part == "hip"],
        )
        assert all(i.resolved and i.resolved_date == date.today() for i in knee)
        assert hip[0].resolved is False
        assert hip[0].resolved_date is None

    async def test_match_is_case_insensitive(self, storage):
        ctx = mock_ctx(storage=storage)
        await report_injury(description="a", body_part="Achilles", ctx=ctx)
        result = await resolve_injury(body_part="ACHILLES", ctx=ctx)
        assert result["resolved_count"] == 1

    async def test_unknown_body_part_returns_error_with_open_list(self, storage):
        ctx = mock_ctx(storage=storage)
        await report_injury(description="a", body_part="knee", ctx=ctx)
        await report_injury(description="b", body_part="hip", ctx=ctx)

        result = await resolve_injury(body_part="shoulder", ctx=ctx)

        assert result["error"] == "No unresolved injury for 'shoulder'."
        assert result["open_injuries"] == ["hip", "knee"]
        # Nothing was resolved
        constraints = storage.load_constraints()
        assert constraints is not None
        assert all(not i.resolved for i in constraints.injuries)

    async def test_already_resolved_injury_not_re_resolved(self, storage):
        ctx = mock_ctx(storage=storage)
        await report_injury(description="a", body_part="knee", ctx=ctx)
        await resolve_injury(body_part="knee", ctx=ctx)
        result = await resolve_injury(body_part="knee", ctx=ctx)
        assert result["error"] == "No unresolved injury for 'knee'."
        assert result["open_injuries"] == []


# ── record_workout_feedback ──────────────────────────────────────────────────


class TestRecordWorkoutFeedback:
    async def test_subjective_only(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await record_workout_feedback(
            feedback_date="2026-07-10",
            workout_type="tempo",
            perceived_effort="hard",
            feeling="good",
            notes="legs heavy",
            ctx=ctx,
        )
        assert result["status"] == "feedback_recorded"
        entries = storage.load_feedback().entries
        assert len(entries) == 1
        assert entries[0].perceived_effort == "hard"
        assert entries[0].date == date(2026, 7, 10)

    async def test_malformed_date_returns_error(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await record_workout_feedback(
            feedback_date="yesterday", workout_type="easy", perceived_effort="easy", ctx=ctx
        )
        assert "error" in result
        assert storage.load_feedback().entries == []

    async def test_defaults_to_today(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await record_workout_feedback(feeling="okay", ctx=ctx)
        assert result["entry"]["date"] == date.today().isoformat()

    async def test_autofill_from_garmin(self, storage):
        garmin = StubGarmin(
            get_activity={
                "summaryDTO": {"distance": 10000.0, "duration": 3000.0, "averageHR": 155},
                "activityTypeDTO": {"typeKey": "running"},
            }
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await record_workout_feedback(activity_id=42, ctx=ctx)
        entry = result["entry"]
        assert entry["actual_distance_m"] == 10_000.0
        assert entry["actual_duration_s"] == 3000.0
        assert entry["avg_hr"] == 155
        assert entry["actual_intensity"] == {"kind": "pace_sec_per_km", "value": 300.0}

    async def test_garmin_failure_is_soft(self, storage):
        garmin = StubGarmin(get_activity=RuntimeError("api down"))
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await record_workout_feedback(activity_id=42, feeling="tired", ctx=ctx)
        assert result["status"] == "feedback_recorded"
        assert result["entry"]["actual_distance_m"] is None

    async def test_no_garmin_client_still_records(self, storage):
        ctx = mock_ctx(storage=storage, garmin=None)
        result = await record_workout_feedback(activity_id=42, ctx=ctx)
        assert result["status"] == "feedback_recorded"

    @staticmethod
    def _plan_with_todays_tempo():
        plan = make_plan(start_offset_days=-7, duration_weeks=4)
        plan.weeks[1].workouts = [
            make_planned_workout(offset_days=0, wtype="tempo", pace=270.0, dist=8.0)
        ]
        return plan

    async def test_planned_targets_autofilled_from_active_plan(self, storage):
        storage.save_plan(self._plan_with_todays_tempo())
        ctx = mock_ctx(storage=storage)
        # workout_type left unset → inherited from the plan
        result = await record_workout_feedback(feeling="good", ctx=ctx)
        entry = result["entry"]
        assert entry["planned_distance_m"] == 8000.0
        assert entry["planned_intensity"] == {"kind": "pace_sec_per_km", "value": 270.0}
        assert entry["workout_type"] == "tempo"

    async def test_explicit_workout_type_not_overridden_by_plan(self, storage):
        storage.save_plan(self._plan_with_todays_tempo())
        ctx = mock_ctx(storage=storage)
        result = await record_workout_feedback(workout_type="intervals", ctx=ctx)
        entry = result["entry"]
        assert entry["workout_type"] == "intervals"
        assert entry["planned_distance_m"] == 8000.0  # targets still auto-filled

    async def test_no_active_plan_leaves_planned_fields_none(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await record_workout_feedback(feeling="good", ctx=ctx)
        entry = result["entry"]
        assert entry["planned_distance_m"] is None
        assert entry["planned_intensity"] is None
        assert entry["workout_type"] == "easy"

    async def test_non_matching_date_leaves_planned_fields_none(self, storage):
        plan = make_plan(start_offset_days=-7, duration_weeks=4)
        plan.weeks[1].workouts = [
            make_planned_workout(offset_days=1, wtype="tempo", pace=270.0, dist=8.0)
        ]
        storage.save_plan(plan)
        ctx = mock_ctx(storage=storage)
        result = await record_workout_feedback(feeling="good", ctx=ctx)  # today
        entry = result["entry"]
        assert entry["planned_distance_m"] is None
        assert entry["planned_intensity"] is None
        assert entry["workout_type"] == "easy"


# ── save_training_plan / archive_active_plan ─────────────────────────────────


class TestSaveTrainingPlan:
    async def test_saves_valid_plan(self, storage):
        plan = make_plan(name="Half Prep")
        ctx = mock_ctx(storage=storage)
        result = await save_training_plan(plan.model_dump_json(), ctx=ctx)
        md_path = result.pop("markdown_path")
        next_steps = result.pop("next_steps")
        assert result == {"status": "plan_saved", "name": "Half Prep", "weeks": 8}
        assert storage.load_active_plan().name == "Half Prep"
        assert Path(md_path).is_file()
        assert "Half Prep" in Path(md_path).read_text(encoding="utf-8")
        assert any("list_watch_workouts" in step for step in next_steps)

    async def test_accepts_plan_object(self, storage):
        """Typed input: clients that follow the JSON schema send an object, not a string."""
        plan = make_plan(name="Object Plan")
        ctx = mock_ctx(storage=storage)
        result = await save_training_plan(plan, ctx=ctx)
        assert result["status"] == "plan_saved"
        assert storage.load_active_plan().name == "Object Plan"

    async def test_invalid_plan_json_returns_error(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await save_training_plan('{"name": "broken"}', ctx=ctx)
        assert "error" in result
        assert "plan_json" in result["error"]
        assert storage.load_active_plan() is None

    async def test_refreshes_markdown_copy_on_resave(self, storage):
        plan = make_plan(name="Half Prep")
        ctx = mock_ctx(storage=storage)
        first = await save_training_plan(plan.model_dump_json(), ctx=ctx)
        plan.weeks[0].notes = "shifted week — tempo on Thu"
        second = await save_training_plan(plan.model_dump_json(), ctx=ctx)
        assert first["markdown_path"] == second["markdown_path"]
        md = Path(second["markdown_path"]).read_text(encoding="utf-8")
        assert "shifted week — tempo on Thu" in md


class TestArchiveActivePlan:
    async def test_no_active_plan_returns_error(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await archive_active_plan(ctx=ctx)
        assert "error" in result

    async def test_archives_and_clears_active(self, storage):
        storage.save_plan(make_plan(name="Spring 10K"))
        ctx = mock_ctx(storage=storage)
        result = await archive_active_plan(outcome_notes="PB by 40s", race_result_s=2360.0, ctx=ctx)
        assert result == {
            "status": "plan_archived",
            "name": "Spring 10K",
            "plan_status": "completed",
        }
        assert storage.load_active_plan() is None
        archived_names = storage.list_archived_plans()
        assert archived_names == ["spring-10k"]
        archived = storage.load_archived_plan("spring-10k")
        assert archived.status == "completed"
        assert archived.outcome_notes == "PB by 40s"
        assert archived.race_result_s == 2360.0

    async def test_archive_as_abandoned(self, storage):
        storage.save_plan(make_plan(name="Aborted Block"))
        ctx = mock_ctx(storage=storage)
        result = await archive_active_plan(outcome_notes="injury", status="abandoned", ctx=ctx)
        assert result["plan_status"] == "abandoned"
        assert storage.load_archived_plan("aborted-block").status == "abandoned"

    async def test_archive_deletes_markdown_copy(self, storage):
        plan = make_plan(name="With Markdown")
        storage.save_plan(plan)
        md = write_plan_markdown(plan)
        assert md.exists()
        ctx = mock_ctx(storage=storage)
        await archive_active_plan(ctx=ctx)
        assert not md.exists()

    async def test_archive_cleans_future_watch_workouts(self, storage):
        storage.save_plan(make_plan(name="Garmin Plan"))
        today = date.today()
        registry = WorkoutRegistry(
            workouts=[
                WorkoutUpload(
                    workout_id=1,
                    name="future",
                    uploaded_at=datetime.now(),
                    schedule_dates=[today + timedelta(days=5)],
                ),
                WorkoutUpload(
                    workout_id=2,
                    name="past",
                    uploaded_at=datetime.now(),
                    schedule_dates=[today - timedelta(days=5)],
                ),
            ]
        )
        storage.save_workout_registry(registry)
        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await archive_active_plan(ctx=ctx)
        assert result["watch_cleanup"] == {"deleted": 1, "errors": []}
        assert ("delete_workout", (1,), {}) in garmin.calls
        reg = storage.load_workout_registry()
        assert reg.find(1).deleted is True
        assert reg.find(2).deleted is False

    async def test_archive_cleanup_watch_false_skips(self, storage):
        storage.save_plan(make_plan(name="No Cleanup"))
        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await archive_active_plan(cleanup_watch=False, ctx=ctx)
        assert "watch_cleanup" not in result
        assert garmin.calls == []


# ── rename_active_plan ───────────────────────────────────────────────────────


class TestRenameActivePlan:
    async def test_no_active_plan(self, storage):
        ctx = mock_ctx(storage=storage)
        result = await rename_active_plan("New Name", ctx=ctx)
        assert "error" in result

    async def test_renames_and_refreshes_markdown(self, storage):
        plan = make_plan(name="Old Ugly Name (from curated markdown)")
        storage.save_plan(plan)
        old_md = write_plan_markdown(plan)
        assert old_md.exists()

        ctx = mock_ctx(storage=storage)
        result = await rename_active_plan("Clean Name", ctx=ctx)

        assert result["status"] == "plan_renamed"
        assert result["old_name"] == "Old Ugly Name (from curated markdown)"
        assert result["new_name"] == "Clean Name"
        assert not old_md.exists()
        renamed = storage.load_active_plan()
        assert renamed.name == "Clean Name"
        new_md = plan_markdown_path(renamed)
        assert new_md.exists()
        assert str(new_md) == result["markdown_copy"]
