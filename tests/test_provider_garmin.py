"""GarminProvider: Garmin payloads → neutral provider models.

Payload shapes mirror what garminconnect returns; only the keys the coach
reads are included.
"""

from __future__ import annotations

from datetime import date

import pytest

from open_coach.providers import WatchProvider
from open_coach.providers.garmin import GarminProvider, parse_garmin_personal_records
from open_coach.workout_dsl import parse_dsl
from tests.conftest import StubGarmin

RUN = {
    "activityId": 111,
    "activityName": "Riverside Running",
    "startTimeLocal": "2026-09-20 07:05:00",
    "distance": 10012.5,
    "duration": 3001.2,
    "averageHR": 148.0,
    "maxHR": 171.0,
    "elevationGain": 42.0,
    "calories": 690.0,
}


def test_garmin_provider_satisfies_the_protocol() -> None:
    assert isinstance(GarminProvider(StubGarmin()), WatchProvider)


async def test_list_runs_maps_fields_and_passes_iso_dates() -> None:
    stub = StubGarmin(get_activities_by_date=[RUN, {"activityId": 222}])
    runs = await GarminProvider(stub).list_runs(date(2026, 9, 1), date(2026, 9, 30))

    assert stub.calls[0] == ("get_activities_by_date", ("2026-09-01", "2026-09-30", "running"), {})
    first, bare = runs
    assert first.activity_id == 111
    assert first.name == "Riverside Running"
    assert first.start_time_local.startswith("2026-09-20")
    assert first.distance_m == 10012.5
    assert first.avg_hr == 148.0
    assert first.calories == 690.0
    # missing keys fall back to neutral defaults
    assert (bare.name, bare.distance_m, bare.duration_s, bare.avg_hr) == ("", 0, 0, None)


async def test_list_runs_handles_none_payload() -> None:
    assert await GarminProvider(StubGarmin()).list_runs(date.today(), date.today()) == []


async def test_activity_detail_keeps_raw_payloads() -> None:
    summary = {"distance": 8000.0, "duration": 2400.0, "averageHR": 140.0, "extra": 1}
    stub = StubGarmin(get_activity={"summaryDTO": summary}, get_activity_splits={"laps": [1]})
    detail = await GarminProvider(stub).activity_detail(111)
    assert (detail.distance_m, detail.duration_s, detail.avg_hr) == (8000.0, 2400.0, 140.0)
    assert detail.summary == summary
    assert detail.splits == {"laps": [1]}


async def test_numbers_keep_their_type() -> None:
    # Integers must not be re-serialised as floats (tool outputs stay identical).
    stub = StubGarmin(
        get_sleep_data={"dailySleepDTO": {"sleepScores": {"overall": {"value": 80}}}},
        get_heart_rates={"restingHeartRate": 50, "maxHeartRate": 160},
    )
    provider = GarminProvider(stub)
    signals = await provider.recovery_signals("2026-09-20")
    hr = await provider.daily_heart_rate("2026-09-20")
    assert signals.model_dump()["sleep_score"] == 80
    assert isinstance(signals.sleep_score, int)
    assert isinstance(hr.resting_hr, int)


async def test_recovery_signals_sub_fetches_fail_independently() -> None:
    stub = StubGarmin(
        get_hrv_data=RuntimeError("boom"),
        get_sleep_data={"dailySleepDTO": {"sleepTimeSeconds": 25200}},
        get_stress_data={"overallStressLevel": 31},
    )
    signals = await GarminProvider(stub).recovery_signals("2026-09-20")
    assert signals.model_dump() == {
        "hrv_weekly_avg": None,
        "hrv_last_night": None,
        "sleep_score": None,
        "sleep_duration_s": 25200,
        "avg_stress": 31,
    }


async def test_training_status_is_none_per_failed_part() -> None:
    stub = StubGarmin(get_max_metrics=RuntimeError("x"), get_training_status={"ok": 1})
    status = await GarminProvider(stub).training_status()
    assert status == {"vo2max": None, "training_status": {"ok": 1}, "training_readiness": None}


async def test_workout_upload_schedule_and_delete() -> None:
    stub = StubGarmin(
        upload_running_workout={"workoutId": 42},
        schedule_workout={"scheduleId": 7},
        get_workouts=[{"workoutId": 42}],
    )
    provider = GarminProvider(stub)
    dsl = parse_dsl("Test", "WARMUP: 10min\nCOOLDOWN: 5min")
    assert await provider.upload_workout(dsl) == 42
    assert await provider.schedule_workout(42, "2026-10-01") == 7
    (listed,) = await provider.list_workouts(10)
    assert (listed.workout_id, listed.name, listed.raw) == (42, "", {"workoutId": 42})
    await provider.unschedule_workout(7)
    await provider.delete_workout(42)
    names = [c[0] for c in stub.calls]
    assert names == [
        "upload_running_workout",
        "schedule_workout",
        "get_workouts",
        "unschedule_workout",
        "delete_workout",
    ]
    assert stub.calls[2][2] == {"start": 0, "limit": 10}


async def test_upload_without_workout_id_raises() -> None:
    provider = GarminProvider(StubGarmin(upload_running_workout={}))
    with pytest.raises(KeyError):
        await provider.upload_workout(parse_dsl("Test", "WARMUP: 10min\nCOOLDOWN: 5min"))


# ── personal records ─────────────────────────────────────────────────────────


def test_parse_personal_records() -> None:
    raw = [
        {
            "typeId": 3,
            "value": 1229.5,
            "activityId": 1,
            "prStartTimeGmtFormatted": "2024-06-20T08:00:00.0",
        },
        {"typeId": 6, "value": 12479.0, "activityId": 2, "prStartTimeGmt": 1713686400000},
        {"typeId": 1, "value": 200.0, "prStartTimeGmtFormatted": "2024-01-01"},  # 1K: not mapped
        {"typeId": 4, "value": None, "prStartTimeGmtFormatted": "2024-01-01"},  # no time
        {"typeId": 5, "value": 5850.0, "prStartTimeGmtFormatted": "not-a-date"},
    ]
    prs = parse_garmin_personal_records(raw)
    assert [(p.distance_label, p.activity_id) for p in prs] == [("5K", 1), ("marathon", 2)]
    five_k = prs[0]
    assert five_k.date == date(2024, 6, 20)
    assert five_k.time_s == pytest.approx(1229.5)
    assert five_k.distance_m == 5000
    assert five_k.source == "platform_pr"
    assert prs[1].date.year == 2024


async def test_personal_records_api_error_returns_empty() -> None:
    provider = GarminProvider(StubGarmin(get_personal_record=RuntimeError("down")))
    assert await provider.personal_records() == []


# ── regressions found against the live account ───────────────────────────────


def _date_only(value: object) -> dict:
    """Mimic garminconnect: calendar-date parameters must be YYYY-MM-DD strings."""
    if not isinstance(value, str):
        raise ValueError("cdate must be a string")
    date.fromisoformat(value)
    return {"cdate": value}


async def test_training_status_passes_todays_iso_date() -> None:
    # Regression: get_training_status(0) / get_training_readiness(0) /
    # get_max_metrics("running") all raised ValueError in garminconnect, so the
    # tool always answered None for the three parts.
    stub = StubGarmin(
        get_max_metrics=_date_only,
        get_training_status=_date_only,
        get_training_readiness=_date_only,
    )
    status = await GarminProvider(stub).training_status()
    today = date.today().isoformat()
    assert status == {
        "vo2max": {"cdate": today},
        "training_status": {"cdate": today},
        "training_readiness": {"cdate": today},
    }


async def test_hrv_is_read_from_hrv_summary() -> None:
    stub = StubGarmin(
        get_hrv_data={"hrvSummary": {"weeklyAvg": 55, "lastNightAvg": 61}, "hrvReadings": []}
    )
    signals = await GarminProvider(stub).recovery_signals("2026-09-20")
    assert (signals.hrv_weekly_avg, signals.hrv_last_night) == (55, 61)


async def test_hrv_top_level_shape_still_read() -> None:
    stub = StubGarmin(get_hrv_data={"weeklyAvg": 50, "lastNightAvg": 52})
    signals = await GarminProvider(stub).recovery_signals("2026-09-20")
    assert (signals.hrv_weekly_avg, signals.hrv_last_night) == (50, 52)
