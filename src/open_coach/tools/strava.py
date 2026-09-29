"""MCP tools for Strava activity retrieval."""

from __future__ import annotations

import asyncio
import logging

from fastmcp import Context

from open_coach.server import mcp

logger = logging.getLogger(__name__)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_strava_activities(
    months: int = 6,
    activity_type: str | None = "Run",
    ctx: Context | None = None,
) -> dict:
    """Fetch Strava activities from the last N months for analysis.

    Args:
        months: Lookback window in months (default 6).
        activity_type: Strava activity type filter — "Run", "Ride", "Swim",
            "Workout", etc. Pass null/None to get every type.
    """
    assert ctx is not None
    strava = ctx.lifespan_context.get("strava")
    if strava is None:
        return {
            "error": (
                "Strava not connected. Run `python scripts/strava_setup.py` once "
                "(needs STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET env vars and a "
                "Strava API app at https://www.strava.com/settings/api)."
            )
        }

    try:
        activities = await asyncio.to_thread(
            strava.fetch_activities, months=months, activity_type=activity_type
        )
    except Exception as err:
        logger.warning("Strava API call failed: %s", err)
        return {"error": f"Strava API call failed: {err}"}

    total_distance_km = sum(a["distance_m"] for a in activities) / 1000
    total_moving_h = sum(a["moving_time_s"] for a in activities) / 3600
    total_elev_m = sum((a["elevation_gain_m"] or 0) for a in activities)

    return {
        "count": len(activities),
        "lookback_months": months,
        "activity_type": activity_type,
        "totals": {
            "distance_km": round(total_distance_km, 1),
            "moving_hours": round(total_moving_h, 1),
            "elevation_gain_m": round(total_elev_m),
        },
        "activities": activities,
    }
