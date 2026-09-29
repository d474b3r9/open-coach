"""Shared test doubles, factories and fixtures for the open_coach test suite.

Provides:
    MockStorage  — in-memory stand-in for CoachStorage (resource/tool tests)
    MockCtx      — minimal FastMCP Context double exposing `lifespan_context`
    mock_ctx     — factory returning a MockCtx typed as a real Context
    StubGarmin   — configurable garminconnect client double (records calls)
    make_plan    — TrainingPlan factory relative to today (optional workouts)
    make_goal    — TrainingGoal factory
    make_profile — AthleteProfile factory (with TrainingPattern)
    make_planned_workout — PlannedWorkout factory
    storage      — fixture: real CoachStorage isolated in tmp_path
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest

from open_coach.models import (
    AthleteProfile,
    FeedbackLog,
    GoalsConfig,
    PlannedWorkout,
    TrainingConstraints,
    TrainingGoal,
    TrainingPattern,
    TrainingPlan,
    TrainingWeek,
    WorkoutFeedback,
)
from open_coach.providers.garmin import GarminProvider
from open_coach.storage import CoachStorage

if TYPE_CHECKING:
    from fastmcp import Context

# Next Monday on or after today — plans generated from here have aligned weekdays.
NEXT_MONDAY = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)

# ── Test doubles ─────────────────────────────────────────────────────────────


class MockStorage:
    """In-memory CoachStorage double for resource/tool tests."""

    def __init__(
        self,
        plan: TrainingPlan | None = None,
        profile: AthleteProfile | None = None,
        goals: GoalsConfig | None = None,
        constraints: TrainingConstraints | None = None,
        feedback: dict[str, FeedbackLog] | None = None,
    ) -> None:
        self._plan = plan
        self._profile = profile
        self._goals = goals
        self._constraints = constraints
        self._feedback: dict[str, FeedbackLog] = dict(feedback or {})

    @staticmethod
    def _current_quarter() -> str:
        now = datetime.now()
        return f"{now.year}-Q{(now.month - 1) // 3 + 1}"

    # ── reads ──

    def load_profile(self) -> AthleteProfile | None:
        return self._profile

    def load_goals(self) -> GoalsConfig | None:
        return self._goals

    def load_constraints(self) -> TrainingConstraints | None:
        return self._constraints

    def load_feedback(self, quarter: str | None = None) -> FeedbackLog:
        q = quarter or self._current_quarter()
        return self._feedback.get(q, FeedbackLog(period=q))

    def load_active_plan(self) -> TrainingPlan | None:
        return self._plan

    def auto_archive_expired(self, grace_days: int = 3) -> TrainingPlan | None:
        return None

    # ── writes (state-capturing) ──

    def save_profile(self, profile: AthleteProfile) -> None:
        self._profile = profile

    def save_goals(self, goals: GoalsConfig) -> None:
        self._goals = goals

    def save_constraints(self, constraints: TrainingConstraints) -> None:
        self._constraints = constraints

    def append_feedback(self, entry: WorkoutFeedback) -> None:
        q = self._current_quarter()
        log = self._feedback.setdefault(q, FeedbackLog(period=q))
        log.entries.append(entry)


class MockCtx:
    """Minimal FastMCP Context double: only `lifespan_context` is needed.

    ``garmin`` is a raw client double (``StubGarmin``) and is wrapped in a
    ``GarminProvider``, so tools see a real provider while tests keep asserting
    on ``stub.calls``. ``watch`` injects any other ``WatchProvider`` directly.
    """

    def __init__(
        self,
        storage: Any = None,
        garmin: Any = None,
        strava: Any = None,
        watch: Any = None,
    ) -> None:
        if watch is None and garmin is not None:
            watch = GarminProvider(garmin)
        self.lifespan_context: dict[str, Any] = {
            "storage": storage,
            "watch": watch,
            "strava": strava,
        }


def mock_ctx(
    storage: Any = None, garmin: Any = None, strava: Any = None, watch: Any = None
) -> Context:
    """Build a MockCtx typed as a real fastmcp Context for tool/resource calls."""
    return cast("Context", MockCtx(storage=storage, garmin=garmin, strava=strava, watch=watch))


class StubGarmin:
    """Configurable garminconnect client double.

    Pass canned responses by method name. A value that is an Exception
    instance is raised; a callable is invoked with the call args; anything
    else is returned as-is (unconfigured methods return None). All calls are
    recorded in `self.calls` as (method_name, args, kwargs).
    """

    def __init__(self, **responses: Any) -> None:
        self._responses = responses
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _respond(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        value = self._responses.get(name)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(*args, **kwargs)
        return value

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args, **kwargs: self._respond(name, *args, **kwargs)

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)


@pytest.fixture(autouse=True)
def _no_real_data_dir_migration(tmp_path_factory: Any, monkeypatch: Any) -> None:
    """Never let a test move the real ~/.garmin-coach to ~/.open-coach."""
    import open_coach.paths as paths

    base = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(paths, "DATA_DIR", base / ".open-coach")
    monkeypatch.setattr(paths, "LEGACY_DATA_DIR", base / ".garmin-coach")


# ── Factories ────────────────────────────────────────────────────────────────


def make_goal(
    distance_m: float = 10000.0,
    weeks_ahead: int | None = None,
    race_name: str = "Test Race",
    *,
    race_date: date | None = None,
    target_time_s: float | None = None,
    priority: Literal["A", "B", "C"] = "A",
) -> TrainingGoal:
    """Build a TrainingGoal.

    race_date resolution: explicit `race_date` wins; else `weeks_ahead` weeks
    after next Monday (weekday-aligned, for plan generation); else today + 30d.
    """
    if race_date is None:
        if weeks_ahead is not None:
            race_date = NEXT_MONDAY + timedelta(weeks=weeks_ahead)
        else:
            race_date = date.today() + timedelta(days=30)
    return TrainingGoal(
        race_name=race_name,
        distance_m=distance_m,
        race_date=race_date,
        target_time_s=target_time_s,
        priority=priority,
    )


def make_profile(
    vdot: float | None = 50.0,
    ctl: float | None = 45.0,
    atl: float | None = 40.0,
    tsb: float | None = 5.0,
    long_run_avg: float = 18.0,
    *,
    weekly_volume_km: float = 50.0,
) -> AthleteProfile:
    """Build an AthleteProfile with a plausible TrainingPattern."""
    pattern = TrainingPattern(
        weekly_volume_km=weekly_volume_km,
        weekly_frequency=4.0,
        long_run_avg_km=long_run_avg,
        easy_pace_avg_sec_per_km=330.0,
        computed_at=datetime.now(),
    )
    return AthleteProfile(
        vdot=vdot,
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        training_pattern=pattern,
        onboarding_complete=True,
    )


def make_planned_workout(
    offset_days: int = 0,
    wtype: str = "easy",
    pace: float | None = None,
    dist: float | None = 8.0,
    description: str | None = None,
    **kwargs: Any,
) -> PlannedWorkout:
    """Build a PlannedWorkout dated relative to today."""
    return PlannedWorkout(
        date=date.today() + timedelta(days=offset_days),
        workout_type=wtype,
        description=description if description is not None else f"{wtype} run",
        target_distance_km=dist,
        target_pace_sec_per_km=pace,
        **kwargs,
    )


def make_plan(
    name: str = "10K Spring",
    start_offset_days: int = -14,
    duration_weeks: int = 8,
    completion: float | None = None,
    workouts_per_week: int = 4,
) -> TrainingPlan:
    """Build a TrainingPlan whose start date is relative to today.

    When `completion` is given, each week gets `workouts_per_week` easy runs
    (every 2 days) with roughly that fraction marked completed.
    """
    today = date.today()
    start = today + timedelta(days=start_offset_days)
    end = start + timedelta(weeks=duration_weeks)
    weeks = []
    for i in range(duration_weeks):
        w_start = start + timedelta(weeks=i)
        workouts: list[PlannedWorkout] = []
        if completion is not None:
            for d in range(workouts_per_week):
                workouts.append(
                    PlannedWorkout(
                        date=w_start + timedelta(days=d * 2),
                        workout_type="easy",
                        description=f"Easy run W{i + 1}D{d + 1}",
                        completed=(d / workouts_per_week) < completion,
                    )
                )
        weeks.append(TrainingWeek(week_number=i + 1, start_date=w_start, workouts=workouts))
    return TrainingPlan(
        name=name,
        goal=TrainingGoal(distance_m=10000, race_date=end),
        start_date=start,
        end_date=end,
        weeks=weeks,
        created_at=datetime.now(),
    )


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_plan_markdown(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep plan markdown copies out of the repo's plans/ directory."""
    monkeypatch.setenv("OPEN_COACH_PLANS_MD_DIR", str(tmp_path / "plans_md"))


@pytest.fixture
def storage(tmp_path: Any) -> CoachStorage:
    """Real CoachStorage isolated in tmp_path (never touches ~/.open-coach)."""
    s = CoachStorage(base_dir=tmp_path / "coach")
    s.ensure_dirs()
    return s
