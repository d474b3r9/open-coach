"""Tests for the Garmin activity MCP tools (tools/activities.py)."""

from __future__ import annotations

from open_coach.tools._common import watch_error
from open_coach.tools.activities import get_activity_details, get_recent_activities
from tests.conftest import StubGarmin, mock_ctx

_RAW_RUN = {
    "activityId": 101,
    "activityName": "Riverside Course à pied",
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2026-07-09 07:30:00",
    "distance": 10000.0,
    "duration": 3000.0,
    "averageHR": 152,
    "maxHR": 171,
    "elevationGain": 45.0,
    "calories": 600,
}


class TestGetRecentActivities:
    async def test_no_garmin_returns_error(self):
        result = await get_recent_activities(ctx=mock_ctx(garmin=None))
        assert result == watch_error()

    async def test_maps_fields_and_computes_pace(self):
        garmin = StubGarmin(get_activities_by_date=[_RAW_RUN])
        result = await get_recent_activities(ctx=mock_ctx(garmin=garmin))
        assert result["count"] == 1
        run = result["activities"][0]
        assert run["activity_id"] == 101
        assert run["sport"] == "running"
        assert run["vendor_type"] == "running"
        assert run["name"] == "Riverside Course à pied"
        assert run["avg_pace_sec_per_km"] == 300.0
        assert run["avg_hr"] == 152

    async def test_zero_distance_gives_none_pace(self):
        raw = dict(_RAW_RUN, distance=0)
        garmin = StubGarmin(get_activities_by_date=[raw])
        result = await get_recent_activities(ctx=mock_ctx(garmin=garmin))
        assert result["activities"][0]["avg_pace_sec_per_km"] is None

    async def test_limit_truncates(self):
        garmin = StubGarmin(get_activities_by_date=[_RAW_RUN] * 5)
        result = await get_recent_activities(limit=2, ctx=mock_ctx(garmin=garmin))
        assert result["count"] == 2


class TestGetActivityDetails:
    async def test_no_garmin_returns_error(self):
        result = await get_activity_details(101, ctx=mock_ctx(garmin=None))
        assert "error" in result

    async def test_returns_summary_and_splits(self):
        garmin = StubGarmin(
            get_activity={
                "summaryDTO": {"distance": 10000.0},
                "activityTypeDTO": {"typeKey": "running"},
            },
            get_activity_splits=[{"lap": 1}],
        )
        result = await get_activity_details(101, ctx=mock_ctx(garmin=garmin))
        assert result["activity_id"] == 101
        assert result["sport"] == "running"
        assert result["summary"] == {"distance": 10000.0}
        assert result["splits"] == [{"lap": 1}]
