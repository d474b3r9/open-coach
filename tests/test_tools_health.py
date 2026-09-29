"""Tests for the Garmin health MCP tools (tools/health.py)."""

from __future__ import annotations

from datetime import date

from open_coach.tools.health import get_health_snapshot, get_training_status
from tests.conftest import StubGarmin, mock_ctx


class TestGetHealthSnapshot:
    async def test_no_garmin_returns_error(self):
        result = await get_health_snapshot(ctx=mock_ctx(garmin=None))
        assert "error" in result

    async def test_happy_path(self):
        garmin = StubGarmin(
            get_heart_rates={"restingHeartRate": 46, "maxHeartRate": 132},
            get_hrv_data={"weeklyAvg": 55, "lastNightAvg": 58},
            get_sleep_data={
                "dailySleepDTO": {
                    "sleepScores": {"overall": {"value": 82}},
                    "sleepTimeSeconds": 27000,
                }
            },
            get_stress_data={"overallStressLevel": 31},
        )
        result = await get_health_snapshot(ctx=mock_ctx(garmin=garmin))
        assert result == {
            "resting_hr": 46,
            "max_hr_today": 132,
            "hrv_weekly_avg": 55,
            "hrv_last_night": 58,
            "sleep_score": 82,
            "sleep_duration_s": 27000,
            "avg_stress": 31,
        }

    async def test_all_fetches_failing_soft_fail_to_none(self):
        err = RuntimeError("api down")
        garmin = StubGarmin(
            get_heart_rates=err,
            get_hrv_data=err,
            get_sleep_data=err,
            get_stress_data=err,
        )
        result = await get_health_snapshot(ctx=mock_ctx(garmin=garmin))
        assert all(v is None for v in result.values())

    async def test_today_resolves_to_iso_date(self):
        garmin = StubGarmin()
        await get_health_snapshot(target_date="today", ctx=mock_ctx(garmin=garmin))
        assert garmin.calls[0] == ("get_heart_rates", (date.today().isoformat(),), {})

    async def test_explicit_date_passed_through(self):
        garmin = StubGarmin()
        await get_health_snapshot(target_date="2026-07-01", ctx=mock_ctx(garmin=garmin))
        assert garmin.calls[0] == ("get_heart_rates", ("2026-07-01",), {})


class TestGetTrainingStatus:
    async def test_no_garmin_returns_error(self):
        result = await get_training_status(ctx=mock_ctx(garmin=None))
        assert "error" in result

    async def test_happy_path(self):
        garmin = StubGarmin(
            get_max_metrics={"vo2MaxValue": 52},
            get_training_status={"status": "PRODUCTIVE"},
            get_training_readiness={"score": 75},
        )
        result = await get_training_status(ctx=mock_ctx(garmin=garmin))
        assert result["vo2max"] == {"vo2MaxValue": 52}
        assert result["training_status"] == {"status": "PRODUCTIVE"}
        assert result["training_readiness"] == {"score": 75}

    async def test_partial_failure_soft_fails(self):
        garmin = StubGarmin(
            get_max_metrics=RuntimeError("nope"),
            get_training_status={"status": "MAINTAINING"},
            get_training_readiness=RuntimeError("nope"),
        )
        result = await get_training_status(ctx=mock_ctx(garmin=garmin))
        assert result["vo2max"] is None
        assert result["training_status"] == {"status": "MAINTAINING"}
        assert result["training_readiness"] is None
