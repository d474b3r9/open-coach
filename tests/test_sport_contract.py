"""Scenarios every sport plugin must pass — run against each registered sport.

The fake sport (tests/fake_sport.py) is registered too: it proves a new sport
plugs into the core (models, storage, plan tools, renderer, metrics, recovery)
with no core change. Adding a real sport adds it to these scenarios for free.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import get_args

import pytest
from pydantic import ValidationError

from open_coach.models import (
    ActivitySummary,
    AthleteProfile,
    GoalsConfig,
    RecoveryAssessment,
    SportProfile,
    TrainingConstraints,
    TrainingGoal,
    TrainingPlan,
)
from open_coach.plan_metrics import recompute_week_actuals
from open_coach.plan_renderer import render_plan_to_markdown
from open_coach.providers.garmin_workout import build_workout
from open_coach.recovery_monitor import recommend_adaptation
from open_coach.sports import registry
from open_coach.sports.base import NON_SPORT_WORKOUT_TYPES, Sport, TargetKind
from open_coach.storage import CoachStorage
from open_coach.tools.plans import generate_training_plan
from open_coach.tools.race import get_race_predictions
from open_coach.tools.training import get_training_zones
from tests.conftest import MockStorage, mock_ctx
from tests.fake_sport import FAKE, FakeSport


@pytest.fixture(autouse=True, scope="module")
def _fake_sport_registered() -> Iterator[None]:
    registry.register_sport(FakeSport())
    yield
    registry.unregister_sport(FAKE)


def _sports() -> list[str]:
    return [*[k for k in registry.supported_sports() if k != FAKE], FAKE]


SPORTS = pytest.mark.parametrize("key", _sports())
RACE_DISTANCE = {"running": 10000.0, FAKE: 40000.0}
RACE_RESULT = {"running": (10000.0, 2700.0), FAKE: (40000.0, 3600.0)}


def _goal(key: str, weeks: int = 10) -> TrainingGoal:
    return TrainingGoal(
        sport=key,
        race_name=f"{key} race",
        distance_m=RACE_DISTANCE.get(key, 10000.0),
        race_date=date.today() + timedelta(weeks=weeks),
    )


def _profile(key: str) -> AthleteProfile:
    sport = registry.get_sport(key)
    fitness = sport.fitness_from_race(*RACE_RESULT.get(key, (10000.0, 2700.0)))
    return AthleteProfile(
        resting_hr=50, max_hr=190, ctl=40.0, sports={key: SportProfile(fitness=fitness)}
    )


def _plan(key: str) -> TrainingPlan:
    return registry.get_sport(key).generate_plan(
        _goal(key), _profile(key), TrainingConstraints(), _next_monday(), "en"
    )


def _next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


# ── Declared shape ────────────────────────────────────────────────────────────


@SPORTS
def test_plugin_satisfies_the_protocol(key: str) -> None:
    sport = registry.get_sport(key)
    assert isinstance(sport, Sport)
    assert sport.key == key


@SPORTS
def test_declared_types_are_consistent(key: str) -> None:
    sport = registry.get_sport(key)
    assert sport.quality_types <= sport.workout_types
    assert not sport.workout_types & NON_SPORT_WORKOUT_TYPES
    assert sport.target_kinds
    assert sport.target_kinds <= set(get_args(TargetKind))
    assert sport.default_speed_mps > 0


def test_unknown_sport_is_rejected_by_the_models() -> None:
    with pytest.raises(ValidationError, match="Unknown sport"):
        TrainingGoal(sport="curling", distance_m=1000)


# ── Profile and fitness ───────────────────────────────────────────────────────


@SPORTS
def test_build_profile_from_no_activity(key: str) -> None:
    profile = registry.get_sport(key).build_profile([], [])
    assert isinstance(profile, SportProfile)


@SPORTS
def test_fitness_marker_uses_the_declared_metric(key: str) -> None:
    sport = registry.get_sport(key)
    fitness = sport.fitness_from_race(*RACE_RESULT.get(key, (10000.0, 2700.0)))
    assert fitness.metric == sport.fitness_metric
    assert sport.describe_fitness(fitness.value)
    assert sport.training_zones(_profile(key), fitness.value)


@SPORTS
def test_activity_intensity_has_the_declared_kind(key: str) -> None:
    sport = registry.get_sport(key)
    intensity = sport.activity_intensity(10000.0, 3000.0)
    if intensity is not None:
        assert intensity.kind == sport.intensity_kind
        assert sport.format_intensity(intensity)


# ── Plans ─────────────────────────────────────────────────────────────────────


@SPORTS
def test_generated_plan_is_valid_and_belongs_to_the_sport(key: str) -> None:
    sport = registry.get_sport(key)
    plan = _plan(key)

    assert plan.goal.sport == key
    assert plan.weeks
    for week in plan.weeks:
        assert set(week.planned_volume) <= {key}
        for w in week.workouts:
            assert plan.sport_of(w) == key
            assert w.workout_type in sport.workout_types | NON_SPORT_WORKOUT_TYPES
    # JSON round trip through the persisted schema
    assert TrainingPlan.model_validate(json.loads(plan.model_dump_json())) == plan


@SPORTS
def test_plan_generation_refuses_a_profile_without_fitness(key: str) -> None:
    with pytest.raises(ValueError, match=r"(?i)available"):
        registry.get_sport(key).generate_plan(
            _goal(key), AthleteProfile(), TrainingConstraints(), _next_monday(), "en"
        )


@SPORTS
def test_plan_renders_and_metrics_recompute(key: str) -> None:
    plan = _plan(key)
    week = plan.weeks[0]
    session = week.workouts[0]
    session.completed = True
    session.actual_duration_s = 3600

    recompute_week_actuals(week, plan.goal.sport)
    markdown = render_plan_to_markdown(plan)

    assert week.actual_volume[key].duration_s == 3600
    assert week.completion_rate > 0
    assert plan.name in markdown


@SPORTS
def test_plan_survives_storage(key: str, tmp_path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    storage.ensure_dirs()
    plan = _plan(key)
    storage.save_plan(plan)
    loaded = storage.load_active_plan()
    assert loaded is not None
    assert loaded.goal.sport == key


@SPORTS
def test_quality_sessions_convert_to_valid_watch_workouts(key: str) -> None:
    sport = registry.get_sport(key)
    profile = _profile(key)
    quality = [w for week in _plan(key).weeks for w in week.workouts if sport.carries_quality(w)]
    assert quality, "the plan should carry at least one quality session"
    converted = [c.dsl for c in (sport.workout_to_dsl(w, profile) for w in quality) if c.ok]
    assert converted
    for dsl in converted:
        assert dsl is not None
        assert dsl.sport == key


def test_garmin_needs_a_mapping_for_a_new_sport() -> None:
    """Step 3 of "Adding a sport": the vendor workout class must be mapped."""
    profile = _profile(FAKE)
    sport = registry.get_sport(FAKE)
    workout = next(
        w for week in _plan(FAKE).weeks for w in week.workouts if sport.carries_quality(w)
    )
    dsl = sport.workout_to_dsl(workout, profile).dsl
    assert dsl is not None
    with pytest.raises(ValueError, match="No Garmin workout mapping"):
        build_workout(dsl)


# ── Recovery ──────────────────────────────────────────────────────────────────


@SPORTS
def test_adaptation_goes_to_the_sport(key: str) -> None:
    plan = _plan(key)
    workout = plan.weeks[0].workouts[0]
    recovery = RecoveryAssessment(
        date=date.today(),
        overall_score=30,
        status="red",
        signals=[],
        summary="",
        recommendations=[],
    )
    rec = recommend_adaptation(recovery, workout, _profile(key), plan.sport_of(workout))
    assert rec.action


# ── Tools, end to end ─────────────────────────────────────────────────────────


async def test_plan_tool_generates_a_fake_sport_plan(storage: CoachStorage) -> None:
    storage.save_profile(_profile(FAKE))
    storage.save_goals(GoalsConfig(goals=[_goal(FAKE)]))

    result = await generate_training_plan(ctx=mock_ctx(storage=storage))

    assert result["status"] == "plan_generated", result
    assert result["start_volume"].endswith(tuple("0123456789"))  # duration, e.g. "4h00"
    saved = storage.load_active_plan()
    assert saved is not None
    assert saved.goal.sport == FAKE


async def test_zone_and_race_tools_dispatch_to_the_sport() -> None:
    storage = MockStorage(
        profile=_profile(FAKE), goals=GoalsConfig(goals=[_goal(FAKE)], updated_at=datetime.now())
    )
    ctx = mock_ctx(storage=storage)

    zones = await get_training_zones(sport=FAKE, ctx=ctx)
    race = await get_race_predictions(ctx=ctx)

    assert "z2" in zones["zones"]
    assert "not available for fakesport" in race["error"]


def test_bootstrap_builds_one_block_per_sport() -> None:
    from open_coach.onboarding import build_profile_from_activities

    today = date.today()
    activities = [
        ActivitySummary(
            activity_id=i, date=today, sport=key, distance_m=10000, duration_s=3000, avg_hr=150
        )
        for i, key in enumerate(_sports())
    ]

    profile = build_profile_from_activities(activities)

    assert set(profile.sports) == set(_sports())
