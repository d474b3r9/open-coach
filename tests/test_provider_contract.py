"""Every tool that uses the watch works with any WatchProvider, not only Garmin.

``FakeWatch`` knows nothing about Garmin payloads: if a tool still reached
into a vendor format, these tests would fail. A new provider (e.g. COROS)
should pass the same scenarios. ``test_every_watch_tool_is_covered`` fails
when a tool starts using the watch without a scenario here.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from open_coach.models import AthleteProfile, PersonalRecord
from open_coach.providers import (
    ActivityDetail,
    DailyHeartRate,
    RecoverySignals,
    RunActivity,
    WatchProvider,
    WatchWorkout,
)
from open_coach.tools import activities, health, memory, plans, recovery, training, workout
from open_coach.tools.activities import get_activity_details, get_recent_runs
from open_coach.tools.health import get_health_snapshot, get_training_status
from open_coach.tools.memory import (
    archive_active_plan,
    bootstrap_athlete_profile,
    record_workout_feedback,
)
from open_coach.tools.plans import sync_upcoming_workouts
from open_coach.tools.recovery import get_adaptive_recommendation, get_recovery_status
from open_coach.tools.training import get_training_load
from open_coach.tools.workout import (
    build_and_push_workout,
    clean_watch_calendar,
    delete_watch_workout,
    list_watch_workouts,
    purge_watch_workouts,
    schedule_watch_workout,
    unschedule_watch_workout,
    upload_workout,
)
from open_coach.workout_dsl import DSLWorkout
from tests.conftest import make_plan, make_planned_workout, mock_ctx

DSL = "WARMUP: lap_button\nREPEAT: 2\n  INTERVAL: 1km @ 4:15-4:25/km\nCOOLDOWN: lap_button"


class FakeWatch:
    """In-memory watch platform with its own (non-Garmin) conventions."""

    name = "fake"

    def __init__(self) -> None:
        today = date.today()
        self.runs = [
            RunActivity(
                activity_id=i,
                name=f"Run {i}",
                start_time_local=f"{today - timedelta(days=i * 3)} 07:00:00",
                distance_m=10000.0,
                duration_s=3000.0,
                avg_hr=150.0,
                max_hr=170.0,
            )
            for i in range(1, 6)
        ]
        self.library: dict[int, str] = {}
        self.schedules: dict[int, tuple[int, str]] = {}
        self.deleted: list[int] = []

    async def list_runs(self, start: date, end: date) -> list[RunActivity]:
        return self.runs

    async def activity_detail(self, activity_id: int) -> ActivityDetail:
        return ActivityDetail(distance_m=8000, duration_s=2400, avg_hr=147.4, summary={"k": 1})

    async def personal_records(self) -> list[PersonalRecord]:
        return []

    async def daily_heart_rate(self, iso_date: str) -> DailyHeartRate:
        return DailyHeartRate(resting_hr=48, max_hr=175)

    async def recovery_signals(self, iso_date: str) -> RecoverySignals:
        return RecoverySignals(hrv_last_night=62, hrv_weekly_avg=60, sleep_score=81, avg_stress=25)

    async def training_status(self) -> dict[str, Any]:
        return {"vo2max": 52}

    async def list_workouts(self, limit: int) -> list[WatchWorkout]:
        return [
            WatchWorkout(workout_id=i, name=n, raw={"id": i, "title": n})
            for i, n in self.library.items()
        ][:limit]

    async def upload_workout(self, dsl: DSLWorkout) -> int:
        workout_id = 100 + len(self.library) + len(self.deleted)
        self.library[workout_id] = dsl.name
        return workout_id

    async def schedule_workout(self, workout_id: int, iso_date: str) -> int:
        schedule_id = 900 + len(self.schedules)
        self.schedules[schedule_id] = (workout_id, iso_date)
        return schedule_id

    async def unschedule_workout(self, schedule_id: int) -> None:
        self.schedules.pop(schedule_id)

    async def delete_workout(self, workout_id: int) -> None:
        self.library.pop(workout_id)
        self.deleted.append(workout_id)


def _ctx(storage, watch: FakeWatch):
    return mock_ctx(storage=storage, watch=watch)


def test_fake_watch_satisfies_the_protocol() -> None:
    assert isinstance(FakeWatch(), WatchProvider)


# ── read tools ────────────────────────────────────────────────────────────────


async def test_activity_tools(storage) -> None:
    ctx = _ctx(storage, FakeWatch())
    runs = await get_recent_runs(ctx=ctx)
    assert runs["count"] == 5
    assert runs["activities"][0]["avg_pace_sec_per_km"] == 300.0
    detail = await get_activity_details(activity_id=1, ctx=ctx)
    assert detail["summary"] == {"k": 1}


async def test_health_and_status_tools(storage) -> None:
    ctx = _ctx(storage, FakeWatch())
    snap = await get_health_snapshot(target_date="2026-09-20", ctx=ctx)
    assert (snap["resting_hr"], snap["hrv_last_night"], snap["sleep_score"]) == (48, 62, 81)
    assert await get_training_status(ctx=ctx) == {"vo2max": 52}


async def test_training_load_and_recovery_tools(storage) -> None:
    storage.save_profile(AthleteProfile(vdot=48.0, tsb=5.0, onboarding_complete=True))
    ctx = _ctx(storage, FakeWatch())
    load = await get_training_load(ctx=ctx)
    assert "error" not in load
    assert load["days_analyzed"] > 0
    status = await get_recovery_status(target_date="2026-09-20", ctx=ctx)
    assert "overall_score" in status
    reco = await get_adaptive_recommendation(target_date="2026-09-20", ctx=ctx)
    assert "error" not in reco


async def test_profile_and_feedback_tools(storage) -> None:
    watch = FakeWatch()
    result = await bootstrap_athlete_profile(ctx=_ctx(storage, watch))
    assert "error" not in result
    assert storage.load_profile().resting_hr == 48

    await record_workout_feedback(activity_id=1, perceived_effort="easy", ctx=_ctx(storage, watch))
    entry = storage.load_feedback().entries[-1]
    assert entry.actual_distance_km == 8.0
    assert entry.avg_hr == 147


# ── workout tools ─────────────────────────────────────────────────────────────


async def test_workout_lifecycle_tools(storage) -> None:
    watch = FakeWatch()
    ctx = _ctx(storage, watch)

    up = await upload_workout(workout_json=DSL, name="W1", ctx=ctx)
    wid = up["workout_id"]
    sch = await schedule_watch_workout(workout_id=wid, target_date="2026-10-14", ctx=ctx)
    assert watch.schedules[sch["schedule_id"]] == (wid, "2026-10-14")
    await unschedule_watch_workout(schedule_id=sch["schedule_id"], ctx=ctx)
    assert watch.schedules == {}

    listed = await list_watch_workouts(ctx=ctx)
    assert listed == {"workouts": [{"id": wid, "title": "W1"}], "count": 1}

    await delete_watch_workout(workout_id=wid, ctx=ctx)
    assert wid not in watch.library
    assert storage.load_workout_registry().find(wid).provider == "fake"


async def test_calendar_cleanup_tools(storage) -> None:
    watch = FakeWatch()
    ctx = _ctx(storage, watch)
    pushed = await build_and_push_workout(
        workout_json=DSL, name="W2", target_date="2026-10-16", ctx=ctx
    )
    assert pushed["status"] == "uploaded_and_scheduled"
    cleaned = await clean_watch_calendar(start_date="2026-10-01", end_date="2026-10-31", ctx=ctx)
    assert cleaned["deleted"] == 1

    await upload_workout(workout_json=DSL, name="W3", ctx=ctx)  # registered
    watch.library[555] = "hand-made"  # not created by the coach
    purged = await purge_watch_workouts(ctx=ctx)
    assert purged["deleted"] == 1
    assert purged["skipped_names"] == ["hand-made"]
    assert list(watch.library) == [555]


async def test_plan_sync_and_archive_tools(storage) -> None:
    storage.save_profile(AthleteProfile(vdot=48.7, onboarding_complete=True))
    tempo = make_planned_workout(
        offset_days=1,
        wtype="tempo",
        pace=260.0,
        dist=8.0,
        description="Tempo 8km incl. 4km @ threshold (4:20/km)",
    )
    plan = make_plan()
    for week in plan.weeks:
        week.workouts = []
    plan.weeks[0].workouts = [tempo]
    storage.save_plan(plan)
    watch = FakeWatch()
    ctx = _ctx(storage, watch)

    result = await sync_upcoming_workouts(ctx=ctx)
    assert result["uploaded"] == 1
    ((wid, day),) = watch.schedules.values()
    assert day == tempo.date.isoformat()

    archived = await archive_active_plan(status="abandoned", ctx=ctx)
    assert archived["watch_cleanup"] == {"deleted": 1, "errors": []}
    assert wid in watch.deleted


# ── coverage guard ────────────────────────────────────────────────────────────


def _uses_watch(fn: Any) -> bool:
    source = inspect.getsource(fn)
    return "get_watch(" in source or "_fetch_recovery_data(" in source


def test_every_watch_tool_is_covered() -> None:
    modules = (activities, health, memory, plans, recovery, training, workout)
    watch_tools = {
        name
        for module in modules
        for name, fn in inspect.getmembers(module, inspect.iscoroutinefunction)
        if fn.__module__ == module.__name__ and not name.startswith("_") and _uses_watch(fn)
    }
    body = Path(__file__).read_text(encoding="utf-8").split("# ── read tools", 1)[1]
    missing = sorted(t for t in watch_tools if f"{t}(" not in body)
    assert len(watch_tools) >= 19
    assert missing == []
