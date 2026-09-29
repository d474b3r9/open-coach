"""Tests for the Strava MCP tool (tools/strava.py)."""

from __future__ import annotations

from open_coach.tools.strava import get_strava_activities
from tests.conftest import StubGarmin, mock_ctx

_ACTIVITIES = [
    {"distance_m": 10000.0, "moving_time_s": 3000, "elevation_gain_m": 50.0},
    {"distance_m": 5000.0, "moving_time_s": 1500, "elevation_gain_m": None},
]


class TestGetStravaActivities:
    async def test_no_strava_returns_error_with_setup_hint(self):
        result = await get_strava_activities(ctx=mock_ctx(strava=None))
        assert "error" in result
        assert "strava_setup.py" in result["error"]

    async def test_happy_path_totals(self):
        strava = StubGarmin(fetch_activities=_ACTIVITIES)
        result = await get_strava_activities(months=3, ctx=mock_ctx(strava=strava))
        assert result["count"] == 2
        assert result["lookback_months"] == 3
        assert result["totals"] == {
            "distance_km": 15.0,
            "moving_hours": 1.2,
            "elevation_gain_m": 50,
        }
        assert result["activities"] == _ACTIVITIES
        # kwargs forwarded to the client
        assert strava.calls[0] == (
            "fetch_activities",
            (),
            {"months": 3, "activity_type": "Run"},
        )

    async def test_api_failure_returns_error(self):
        strava = StubGarmin(fetch_activities=RuntimeError("401 unauthorized"))
        result = await get_strava_activities(ctx=mock_ctx(strava=strava))
        assert result == {"error": "Strava API call failed: 401 unauthorized"}

    async def test_activity_type_none_passed_through(self):
        strava = StubGarmin(fetch_activities=[])
        result = await get_strava_activities(activity_type=None, ctx=mock_ctx(strava=strava))
        assert result["count"] == 0
        assert strava.calls[0][2]["activity_type"] is None
