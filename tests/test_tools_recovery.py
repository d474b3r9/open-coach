"""Tests for the recovery MCP tools (tools/recovery.py)."""

from __future__ import annotations

from datetime import date

from open_coach.models import AthleteProfile, PlannedWorkout
from open_coach.sports.running import pace
from open_coach.tools.recovery import (
    get_adaptive_recommendation,
    get_recovery_status,
)
from tests.conftest import MockStorage, StubGarmin, make_plan, mock_ctx, running_profile


def _healthy_garmin() -> StubGarmin:
    return StubGarmin(
        get_hrv_data={"weeklyAvg": 50, "lastNightAvg": 52},
        get_sleep_data={
            "dailySleepDTO": {
                "sleepScores": {"overall": {"value": 85}},
                "sleepTimeSeconds": 28800,
            }
        },
        get_stress_data={"overallStressLevel": 25},
    )


class TestGetRecoveryStatus:
    async def test_tsb_comes_from_the_watch_not_the_stale_profile(self):
        # Regression: TSB was read from the profile snapshot (last bootstrap,
        # possibly months old) instead of the watch history.
        from datetime import timedelta

        runs = [
            {
                "startTimeLocal": f"{date.today() - timedelta(days=d)} 08:00:00",
                "averageHR": 168,
                "duration": 5400.0,
            }
            for d in range(0, 10)
        ]
        garmin = StubGarmin(get_activities_by_date=runs)
        storage = MockStorage(profile=AthleteProfile(tsb=15.0))  # stale, "fresh" snapshot
        result = await get_recovery_status(ctx=mock_ctx(storage=storage, garmin=garmin))
        tsb = next(s for s in result["signals"] if s["name"] == "TSB")
        assert tsb["available"]
        assert "15" not in tsb["value"]
        assert tsb["status"] != "green"

    async def test_tsb_falls_back_to_profile_without_hr_history(self):
        storage = MockStorage(profile=AthleteProfile(tsb=15.0))
        result = await get_recovery_status(ctx=mock_ctx(storage=storage, garmin=StubGarmin()))
        tsb = next(s for s in result["signals"] if s["name"] == "TSB")
        assert "15" in tsb["value"]

    async def test_reports_the_requested_date(self):
        # Regression: target_date was fetched but the assessment said "today".
        ctx = mock_ctx(storage=MockStorage(), garmin=_healthy_garmin())
        result = await get_recovery_status(target_date="2026-09-28", ctx=ctx)
        assert result["date"] == "2026-09-28"
        assert all(s["available"] for s in result["signals"] if s["name"] in ("HRV", "Sleep"))

    async def test_works_without_garmin(self):
        ctx = mock_ctx(storage=MockStorage(), garmin=None)
        result = await get_recovery_status(ctx=ctx)
        assert result["status"] in ("green", "yellow", "red")
        assert result["date"] == date.today().isoformat()

    async def test_happy_path_with_signals(self):
        storage = MockStorage(profile=AthleteProfile(tsb=5.0))
        ctx = mock_ctx(storage=storage, garmin=_healthy_garmin())
        result = await get_recovery_status(ctx=ctx)

        assert 0 <= result["overall_score"] <= 100
        names = [s["name"] for s in result["signals"]]
        assert "HRV" in names
        assert "Sleep" in names
        assert result["summary"]
        assert isinstance(result["recommendations"], list)

    async def test_garmin_failures_are_soft(self):
        err = RuntimeError("api down")
        garmin = StubGarmin(get_hrv_data=err, get_sleep_data=err, get_stress_data=err)
        ctx = mock_ctx(storage=MockStorage(), garmin=garmin)
        result = await get_recovery_status(ctx=ctx)
        assert result["status"] in ("green", "yellow", "red")

    async def test_explicit_date_passed_to_garmin(self):
        garmin = _healthy_garmin()
        ctx = mock_ctx(storage=MockStorage(), garmin=garmin)
        result = await get_recovery_status(target_date="2026-07-01", ctx=ctx)
        assert garmin.calls[0][1] == ("2026-07-01",)
        assert result["status"] in ("green", "yellow", "red")


class TestGetAdaptiveRecommendation:
    async def test_no_plan_still_recommends(self):
        ctx = mock_ctx(storage=MockStorage(), garmin=None)
        result = await get_adaptive_recommendation(ctx=ctx)
        assert result["recommendation"]["action"] in (
            "proceed",
            "reduce_intensity",
            "reduce_volume",
            "swap_to_easy",
            "rest_day",
        )
        assert "planned_workout" not in result

    async def test_todays_planned_workout_is_included(self):
        plan = make_plan(start_offset_days=-3, duration_weeks=2)
        plan.weeks[0].workouts = [
            PlannedWorkout(
                date=date.today(),
                workout_type="tempo",
                description="4k tempo",
                target_intensity=pace(270.0),
            )
        ]
        storage = MockStorage(plan=plan, profile=running_profile(vdot=48.0, tsb=2.0))
        ctx = mock_ctx(storage=storage, garmin=_healthy_garmin())
        result = await get_adaptive_recommendation(ctx=ctx)

        assert result["planned_workout"] == {
            "date": date.today().isoformat(),
            "type": "tempo",
            "description": "4k tempo",
        }
        assert result["recovery"]["status"] in ("green", "yellow", "red")
        assert result["recommendation"]["reasoning"]

    async def test_completed_workout_is_ignored(self):
        plan = make_plan(start_offset_days=-3, duration_weeks=2)
        plan.weeks[0].workouts = [
            PlannedWorkout(
                date=date.today(),
                workout_type="easy",
                description="done already",
                completed=True,
            )
        ]
        storage = MockStorage(plan=plan)
        ctx = mock_ctx(storage=storage, garmin=None)
        result = await get_adaptive_recommendation(ctx=ctx)
        assert "planned_workout" not in result
