"""MCP tools for activity retrieval and analysis (via the watch provider)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastmcp import Context

from open_coach.server import mcp
from open_coach.sports.base import ActivitySport
from open_coach.sports.running import RUNNING, avg_pace_sec_per_km
from open_coach.tools._common import (
    compact_payload,
    get_watch,
    watch_error,
)

logger = logging.getLogger(__name__)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_recent_activities(
    days: int = 30,
    limit: int = 20,
    sport: ActivitySport | None = None,
    ctx: Context | None = None,
) -> dict:
    """Get recent activities from the watch platform, every sport by default.

    Each activity carries ``sport`` (a coached sport, or ``other``) and
    ``vendor_type`` (the platform's own type, e.g. ``trail_running``).

    Args:
        days: Number of days to look back (default 30).
        limit: Maximum number of activities to return (default 20).
        sport: Only this sport (e.g. ``running``, or ``other``); None = all.

    Returns:
        {"activities": [...], "count": int} or {"error": str}.
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()

    activities = await watch.list_activities(date.today() - timedelta(days=days), date.today())
    if sport is not None:
        activities = [a for a in activities if a.sport == sport]
    results = []
    for a in activities[:limit]:
        row = {
            "activity_id": a.activity_id,
            "sport": a.sport,
            "vendor_type": a.vendor_type,
            "name": a.name,
            "date": a.start_time_local,
            "distance_m": a.distance_m,
            "duration_s": a.duration_s,
            "avg_hr": a.avg_hr,
            "max_hr": a.max_hr,
            "elevation_gain_m": a.elevation_gain_m,
            "calories": a.calories,
        }
        if a.sport == RUNNING:
            row["avg_pace_sec_per_km"] = avg_pace_sec_per_km(a.duration_s, a.distance_m)
        results.append(row)
    return {"activities": results, "count": len(results)}


@mcp.tool(annotations={"readOnlyHint": True})
async def get_activity_details(
    activity_id: int, compact: bool = True, ctx: Context | None = None
) -> dict:
    """Get detailed metrics for a specific activity including splits, HR zones, and laps.

    Args:
        activity_id: The activity ID on the watch platform.
        compact: Drop empty fields and round floats (default True). Set False
            only to see the untouched vendor payload.
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()

    detail = await watch.activity_detail(activity_id)

    result = {
        "activity_id": activity_id,
        "sport": detail.sport,
        "summary": detail.summary,
        "splits": detail.splits,
    }
    return compact_payload(result) if compact else result
