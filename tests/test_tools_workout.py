"""Tests for the Garmin workout MCP tools (tools/workout.py)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from open_coach.models import WorkoutUpload
from open_coach.tools._common import watch_error
from open_coach.tools.workout import (
    _load_dsl,
    build_and_push_workout,
    clean_watch_calendar,
    delete_watch_workout,
    list_watch_workouts,
    purge_watch_workouts,
    schedule_watch_workout,
    unschedule_watch_workout,
    upload_workout,
)
from tests.conftest import StubGarmin, mock_ctx

# ── Helpers ──────────────────────────────────────────────────────────────────

_WORKOUT_JSON = json.dumps(
    {
        "name": "10x1min @ threshold",
        "steps": [
            {"type": "warmup", "duration": {"seconds": 600}},
            {
                "type": "repeat",
                "count": 10,
                "steps": [
                    {
                        "type": "interval",
                        "duration": {"seconds": 60},
                        "pace": {"min_sec_per_km": 250, "max_sec_per_km": 265},
                    },
                    {"type": "recovery", "duration": {"seconds": 60}},
                ],
            },
            {"type": "cooldown", "duration": {"seconds": 600}},
        ],
    }
)


def _register(storage, workout_id: int, name: str, schedule_dates=()) -> None:
    storage.register_workout_upload(
        WorkoutUpload(workout_id=workout_id, name=name, uploaded_at=datetime.now())
    )
    for i, d in enumerate(schedule_dates):
        storage.record_workout_schedule(workout_id, 1000 + i, d.isoformat())


_TEXT_DSL = (
    "WARMUP: 10min\nREPEAT: 10\n  INTERVAL: 1min @ 4:10-4:25/km\n  RECOVERY: 1min\nCOOLDOWN: 10min"
)


# ── _load_dsl ────────────────────────────────────────────────────────────────


class TestLoadDsl:
    def test_json_input(self):
        dsl = _load_dsl(_WORKOUT_JSON)
        assert dsl.name == "10x1min @ threshold"

    def test_text_input_with_name(self):
        dsl = _load_dsl(_TEXT_DSL, name="10x1min @ threshold")
        assert dsl.name == "10x1min @ threshold"
        assert dsl.estimated_duration_s > 0

    def test_text_input_without_name_raises(self):
        with pytest.raises(ValueError, match="name is required"):
            _load_dsl(_TEXT_DSL)


# ── upload_workout ───────────────────────────────────────────────────────────


class TestUploadWorkout:
    async def test_uploads_and_registers(self, storage):
        garmin = StubGarmin(upload_running_workout={"workoutId": 555})
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await upload_workout(_WORKOUT_JSON, ctx=ctx)

        assert result["workout_id"] == 555
        assert result["name"] == "10x1min @ threshold"
        assert result["status"] == "uploaded"
        assert result["estimated_duration_s"] > 0

        entry = storage.load_workout_registry().find(555)
        assert entry is not None
        assert entry.deleted is False

    async def test_invalid_json_returns_error(self, storage):
        ctx = mock_ctx(storage=storage, garmin=StubGarmin())
        result = await upload_workout("{not json", ctx=ctx)
        assert "error" in result
        assert "Invalid workout definition" in result["error"]

    async def test_text_dsl_without_name_returns_error(self, storage):
        ctx = mock_ctx(storage=storage, garmin=StubGarmin())
        result = await upload_workout(_TEXT_DSL, ctx=ctx)
        assert "error" in result
        assert "name is required" in result["error"]

    async def test_build_and_push_bad_date_returns_error(self, storage):
        garmin = StubGarmin(upload_running_workout={"workoutId": 1})
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await build_and_push_workout(_WORKOUT_JSON, "2026-13-45", ctx=ctx)
        assert "error" in result
        assert "target_date" in result["error"]
        assert storage.load_workout_registry().find(1) is None

    async def test_build_and_push_invalid_json_returns_error(self, storage):
        ctx = mock_ctx(storage=storage, garmin=StubGarmin())
        result = await build_and_push_workout("{not json", "2026-07-10", ctx=ctx)
        assert "error" in result

    async def test_text_dsl_upload(self, storage):
        garmin = StubGarmin(upload_running_workout={"workoutId": 900})
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await upload_workout(_TEXT_DSL, name="Threshold — 3×10 min", ctx=ctx)
        assert result["workout_id"] == 900
        assert result["name"] == "Threshold — 3×10 min"
        assert storage.load_workout_registry().find(900) is not None

    async def test_disconnected_returns_error(self, storage):
        result = await upload_workout(_WORKOUT_JSON, ctx=mock_ctx(storage=storage, garmin=None))
        assert result == watch_error()


# ── schedule_watch_workout ──────────────────────────────────────────────────


class TestScheduleWorkout:
    async def test_schedules_and_records(self, storage):
        _register(storage, 555, "w")
        garmin = StubGarmin(schedule_workout={"workoutScheduleId": 777})
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await schedule_watch_workout(555, "2026-07-15", ctx=ctx)

        assert result == {
            "schedule_id": 777,
            "workout_id": 555,
            "date": "2026-07-15",
            "status": "scheduled",
        }
        entry = storage.load_workout_registry().find(555)
        assert entry.schedule_ids == [777]
        assert entry.schedule_dates == [date(2026, 7, 15)]

    async def test_falls_back_to_schedule_id_key(self, storage):
        _register(storage, 1, "w")
        garmin = StubGarmin(schedule_workout={"scheduleId": 42})
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await schedule_watch_workout(1, "2026-07-15", ctx=ctx)
        assert result["schedule_id"] == 42


# ── build_and_push_workout ───────────────────────────────────────────────────


class TestBuildAndPushWorkout:
    async def test_uploads_then_schedules(self, storage):
        garmin = StubGarmin(
            upload_running_workout={"workoutId": 321},
            schedule_workout={"workoutScheduleId": 654},
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await build_and_push_workout(_WORKOUT_JSON, "2026-07-20", ctx=ctx)

        assert result["workout_id"] == 321
        assert result["schedule_id"] == 654
        assert result["status"] == "uploaded_and_scheduled"

        entry = storage.load_workout_registry().find(321)
        assert entry.schedule_dates == [date(2026, 7, 20)]

    async def test_requires_garmin(self, storage):
        ctx = mock_ctx(storage=storage, garmin=None)
        result = await build_and_push_workout(_WORKOUT_JSON, "2026-07-20", ctx=ctx)
        assert result == watch_error()


# ── delete / unschedule ──────────────────────────────────────────────────────


class TestDeleteAndUnschedule:
    async def test_delete_marks_registry(self, storage):
        _register(storage, 555, "w")
        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await delete_watch_workout(555, ctx=ctx)

        assert result == {"workout_id": 555, "status": "deleted"}
        assert garmin.called("delete_workout")
        assert storage.load_workout_registry().find(555).deleted is True

    async def test_unschedule(self, storage):
        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await unschedule_watch_workout(777, ctx=ctx)
        assert result == {"schedule_id": 777, "status": "unscheduled"}
        assert garmin.called("unschedule_workout")


# ── list_watch_workouts ─────────────────────────────────────────────────────


class TestListWorkouts:
    async def test_lists_templates(self, storage):
        garmin = StubGarmin(get_workouts=[{"workoutId": 1}, {"workoutId": 2}])
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await list_watch_workouts(ctx=ctx)
        assert result["count"] == 2

    async def test_requires_garmin(self, storage):
        result = await list_watch_workouts(ctx=mock_ctx(storage=storage, garmin=None))
        assert result == watch_error()


# ── clean_watch_calendar ────────────────────────────────────────────────────


class TestCleanGarminCalendar:
    async def test_deletes_only_in_range(self, storage):
        today = date.today()
        _register(storage, 1, "in-range", schedule_dates=[today + timedelta(days=2)])
        _register(storage, 2, "out-of-range", schedule_dates=[today + timedelta(days=40)])
        garmin = StubGarmin()
        ctx = mock_ctx(storage=storage, garmin=garmin)

        result = await clean_watch_calendar(
            today.isoformat(), (today + timedelta(days=7)).isoformat(), ctx=ctx
        )
        assert result["deleted"] == 1
        assert result["skipped"] == 1
        assert result["status"] == "complete"

        registry = storage.load_workout_registry()
        assert registry.find(1).deleted is True
        assert registry.find(2).deleted is False

    async def test_delete_error_reported(self, storage):
        today = date.today()
        _register(storage, 1, "w", schedule_dates=[today])
        garmin = StubGarmin(delete_workout=RuntimeError("boom"))
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await clean_watch_calendar(today.isoformat(), today.isoformat(), ctx=ctx)
        assert result["deleted"] == 0
        assert result["status"] == "partial"
        assert result["errors"][0]["workout_id"] == 1


# ── purge_watch_workouts ────────────────────────────────────────────────────


class TestPurgeWorkouts:
    async def test_purges_only_registered_by_default(self, storage):
        _register(storage, 1, "coach workout")
        garmin = StubGarmin(
            get_workouts=[
                {"workoutId": 1, "workoutName": "coach workout"},
                {"workoutId": 2, "workoutName": "hand-made"},
            ]
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await purge_watch_workouts(ctx=ctx)

        assert result["templates_in_library"] == 2
        assert result["deleted"] == 1
        assert result["skipped_unregistered"] == 1
        assert result["skipped_names"] == ["hand-made"]
        assert storage.load_workout_registry().find(1).deleted is True

    async def test_include_unregistered_deletes_everything(self, storage):
        _register(storage, 1, "coach workout")
        garmin = StubGarmin(
            get_workouts=[
                {"workoutId": 1, "workoutName": "coach workout"},
                {"workoutId": 2, "workoutName": "hand-made"},
            ]
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await purge_watch_workouts(include_unregistered=True, ctx=ctx)
        assert result["deleted"] == 2
        assert result["skipped_unregistered"] == 0

    async def test_delete_errors_are_collected(self, storage):
        _register(storage, 1, "w")
        garmin = StubGarmin(
            get_workouts=[{"workoutId": 1, "workoutName": "w"}],
            delete_workout=RuntimeError("400"),
        )
        ctx = mock_ctx(storage=storage, garmin=garmin)
        result = await purge_watch_workouts(ctx=ctx)
        assert result["deleted"] == 0
        assert result["status"] == "partial"
        assert result["errors"][0]["workout_id"] == 1
