"""MCP tools for activity retrieval and analysis (via the watch provider)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastmcp import Context

from open_coach.server import mcp
from open_coach.tools._common import (
    avg_pace_sec_per_km,
    compact_payload,
    get_watch,
    watch_error,
)

logger = logging.getLogger(__name__)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_recent_runs(days: int = 30, limit: int = 20, ctx: Context | None = None) -> dict:
    """Get recent running activities from the watch platform.

    Args:
        days: Number of days to look back (default 30).
        limit: Maximum number of activities to return (default 20).

    Returns:
        {"activities": [...], "count": int} or {"error": str}.
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()

    runs = await watch.list_runs(date.today() - timedelta(days=days), date.today())
    results = []
    for a in runs[:limit]:
        results.append(
            {
                "activity_id": a.activity_id,
                "name": a.name,
                "date": a.start_time_local,
                "distance_m": a.distance_m,
                "duration_s": a.duration_s,
                "avg_hr": a.avg_hr,
                "max_hr": a.max_hr,
                "avg_pace_sec_per_km": avg_pace_sec_per_km(a.duration_s, a.distance_m),
                "elevation_gain_m": a.elevation_gain_m,
                "calories": a.calories,
            }
        )
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
        "summary": detail.summary,
        "splits": detail.splits,
    }
    return compact_payload(result) if compact else result
