"""MCP tools for health metrics (via the watch provider)."""

from __future__ import annotations

import logging

from fastmcp import Context

from open_coach.server import mcp
from open_coach.tools._common import get_watch, resolve_target_date, watch_error

logger = logging.getLogger(__name__)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_health_snapshot(target_date: str = "today", ctx: Context | None = None) -> dict:
    """Get current health metrics: resting HR, HRV, sleep score, stress, body battery.

    Args:
        target_date: Date string (YYYY-MM-DD) or "today" (default).
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()

    d = resolve_target_date(target_date)

    snapshot: dict = {"resting_hr": None, "max_hr_today": None}
    try:
        hr = await watch.daily_heart_rate(d)
        snapshot["resting_hr"] = hr.resting_hr
        snapshot["max_hr_today"] = hr.max_hr
    except Exception as err:
        logger.debug("Heart rate fetch failed: %s", err)

    snapshot.update((await watch.recovery_signals(d)).model_dump())
    return snapshot


@mcp.tool(annotations={"readOnlyHint": True})
async def get_training_status(ctx: Context | None = None) -> dict:
    """Get the watch platform's training status, VO2max estimate, and recovery time."""
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()

    return await watch.training_status()
