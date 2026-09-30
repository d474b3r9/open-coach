"""Sport-agnostic I/O: activities of every sport, heart-rate targets, sport-checked DSL."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import ValidationError

from open_coach.providers.garmin import GarminProvider
from open_coach.providers.garmin_workout import build_workout
from open_coach.tools._common import training_load_as_of
from open_coach.workout_dsl import DSLWorkout, HeartRateTarget, IntervalStep, parse_dsl
from tests.conftest import MockStorage, StubGarmin

if TYPE_CHECKING:
    from open_coach.storage import CoachStorage


def _raw(activity_id: int, type_key: str | None, day: str = "2026-09-20") -> dict:
    raw: dict = {
        "activityId": activity_id,
        "startTimeLocal": f"{day} 07:00:00",
        "distance": 10000.0,
        "duration": 3600.0,
        "averageHR": 150.0,
    }
    if type_key is not None:
        raw["activityType"] = {"typeKey": type_key}
    return raw


RAW = [
    _raw(1, "running"),
    _raw(2, "trail_running"),
    _raw(3, "treadmill_running"),
    _raw(4, "road_biking"),
    _raw(5, None),
]


async def test_list_activities_maps_every_garmin_type_to_a_sport() -> None:
    stub = StubGarmin(get_activities_by_date=RAW)

    activities = await GarminProvider(stub).list_activities(date(2026, 9, 1), date(2026, 9, 30))

    assert stub.calls[0] == ("get_activities_by_date", ("2026-09-01", "2026-09-30"), {})
    assert [a.sport for a in activities] == ["running", "running", "running", "other", "other"]
    assert [a.vendor_type for a in activities] == [
        "running",
        "trail_running",
        "treadmill_running",
        "road_biking",
        "",
    ]


async def test_list_activities_filters_by_sport() -> None:
    provider = GarminProvider(StubGarmin(get_activities_by_date=RAW))

    runs = await provider.list_activities(
        date(2026, 9, 1), date(2026, 9, 30), frozenset({"running"})
    )

    assert [a.activity_id for a in runs] == [1, 2, 3]


async def test_activity_detail_carries_its_sport() -> None:
    stub = StubGarmin(
        get_activity={"activityTypeDTO": {"typeKey": "lap_swimming"}, "summaryDTO": {}},
        get_activity_splits={},
    )

    detail = await GarminProvider(stub).activity_detail(9)

    assert detail.sport == "other"


async def test_training_load_counts_every_sport() -> None:
    run_only = GarminProvider(StubGarmin(get_activities_by_date=[_raw(1, "running")]))
    with_ride = GarminProvider(
        StubGarmin(get_activities_by_date=[_raw(1, "running"), _raw(4, "road_biking")])
    )
    as_of = date(2026, 9, 20)
    storage = cast("CoachStorage", MockStorage())

    alone = await training_load_as_of(run_only, storage, as_of)
    both = await training_load_as_of(with_ride, storage, as_of)

    assert alone.point is not None
    assert both.point is not None
    assert both.activities_count == 2
    assert both.point.atl > alone.point.atl


def test_text_dsl_parses_heart_rate_targets() -> None:
    dsl = parse_dsl("HR intervals", "REPEAT: 3\n  INTERVAL: 5min @ 150-160bpm\n", "running")

    [block] = dsl.steps
    [step] = block.steps  # type: ignore[union-attr]
    assert isinstance(step, IntervalStep)
    assert step.target == HeartRateTarget(min_bpm=150, max_bpm=160)


def test_heart_rate_range_must_be_increasing() -> None:
    with pytest.raises(ValidationError):
        HeartRateTarget(min_bpm=160, max_bpm=150)


def test_dsl_requires_a_sport() -> None:
    with pytest.raises(ValidationError):
        DSLWorkout.model_validate({"name": "x", "steps": []})


def test_garmin_heart_rate_target_payload() -> None:
    dsl = parse_dsl("HR", "REPEAT: 1\n  INTERVAL: 20min @ 140-150bpm\n", "running")

    payload = build_workout(dsl).to_dict()

    step = payload["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"][0]
    assert step["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert step["targetValueOne"] == 140
    assert step["targetValueTwo"] == 150
    assert payload["sportType"]["sportTypeKey"] == "running"


def test_garmin_pace_target_payload_is_unchanged() -> None:
    dsl = parse_dsl("Pace", "REPEAT: 1\n  INTERVAL: 1km @ 4:00-4:10/km\n", "running")

    step = build_workout(dsl).to_dict()["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"][0]

    assert step["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert step["targetValueOne"] == round(1000 / 240, 4)  # faster bound first
    assert step["targetValueTwo"] == round(1000 / 250, 4)
