"""MCP tools for VDOT calculation, training zones, and training load."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastmcp import Context

from open_coach.server import mcp
from open_coach.sports.running import vdot_of
from open_coach.tools._common import (
    LOAD_WINDOW_DAYS,
    get_watch,
    training_load_as_of,
    watch_error,
)
from open_coach.training_load import interpret_tsb
from open_coach.vdot import (
    HALF_MARATHON_M,
    MARATHON_M,
    calculate_vdot,
    format_pace,
    format_time,
    predict_time,
    training_paces,
)
from open_coach.zones import hr_zones_karvonen, merge_zones, pace_zones_from_vdot


@mcp.tool(annotations={"readOnlyHint": True})
async def calculate_vdot_from_race(distance_meters: float, time_seconds: float) -> dict:
    """Calculate VDOT and training paces from a race result or time trial.

    Args:
        distance_meters: Race distance in meters (e.g. 5000, 10000, 21097.5, 42195).
        time_seconds: Finish time in seconds.

    Returns:
        Dict with VDOT value, training paces, and race predictions.
    """
    vdot = calculate_vdot(distance_meters, time_seconds)
    paces = training_paces(vdot)

    predictions = {}
    for name, dist in [
        ("5K", 5000),
        ("10K", 10000),
        ("Half", HALF_MARATHON_M),
        ("Marathon", MARATHON_M),
    ]:
        t = predict_time(vdot, dist)
        predictions[name] = format_time(t)

    formatted_paces = {}
    for zone, (fast, slow) in paces.items():
        formatted_paces[zone] = f"{format_pace(fast)} - {format_pace(slow)}/km"

    return {
        "vdot": round(vdot, 1),
        "training_paces": formatted_paces,
        "race_predictions": predictions,
    }


@mcp.tool(annotations={"readOnlyHint": True})
async def get_training_zones(
    vdot: float | None = None,
    race_distance_m: float | None = None,
    race_time_s: float | None = None,
    ctx: Context | None = None,
) -> dict:
    """Calculate Daniels training zones (pace + HR) from VDOT or a recent race.

    Provide either vdot directly, or race_distance_m + race_time_s to compute it.

    Args:
        vdot: VDOT value (if known).
        race_distance_m: Race distance in meters (alternative to vdot).
        race_time_s: Race time in seconds (alternative to vdot).
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    profile = storage.load_profile()

    if vdot is None:
        if race_distance_m and race_time_s:
            vdot = calculate_vdot(race_distance_m, race_time_s)
        elif (profile_vdot := vdot_of(profile)) is not None:
            vdot = profile_vdot
        else:
            return {"error": "No VDOT available. Provide race data or run onboarding first."}

    zones = pace_zones_from_vdot(vdot)
    hr_source: dict[str, Any] | None = None
    if (
        profile is not None
        and profile.resting_hr is not None
        and profile.max_hr is not None
        and profile.resting_hr < profile.max_hr
    ):
        zones = merge_zones(zones, hr_zones_karvonen(profile.resting_hr, profile.max_hr))
        hr_source = {
            "resting_hr": profile.resting_hr,
            "max_hr": profile.max_hr,
            "method": "karvonen",
        }

    result: dict[str, Any] = {"vdot": round(vdot, 1), "zones": {}}
    for zone_name in ["easy", "marathon", "threshold", "interval", "repetition"]:
        zone_info = getattr(zones, zone_name)
        result["zones"][zone_name] = {
            "pace": (
                f"{format_pace(zone_info.pace.min_pace_sec_per_km)}"
                f" - {format_pace(zone_info.pace.max_pace_sec_per_km)}/km"
            )
            if zone_info.pace
            else None,
            "hr": (f"{zone_info.hr.min_bpm}-{zone_info.hr.max_bpm} bpm" if zone_info.hr else None),
        }

    if hr_source is not None:
        result["hr_source"] = hr_source
    else:
        result["hint"] = (
            "HR zones unavailable — set resting_hr and max_hr via "
            "update_athlete_profile or run bootstrap_athlete_profile."
        )

    return result


@mcp.tool(annotations={"readOnlyHint": True})
async def get_training_load(days: int = LOAD_WINDOW_DAYS, ctx: Context | None = None) -> dict:
    """Calculate CTL/ATL/TSB (fitness/fatigue/form) from recent training history.

    Args:
        days: Number of days of history (default 180: shorter windows understate CTL).
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()

    storage = ctx.lifespan_context["storage"]
    today = date.today()
    snapshot = await training_load_as_of(watch, storage, today, days)
    if snapshot.point is None:
        return {"error": "No activities with HR data found."}
    current = snapshot.point

    return {
        "ctl_fitness": round(current.ctl, 1),
        "atl_fatigue": round(current.atl, 1),
        "tsb_form": round(current.tsb, 1),
        "interpretation": interpret_tsb(current.tsb),
        "threshold_hr_used": snapshot.threshold_hr,
        "days_analyzed": days,
        "activities_count": snapshot.runs_count,
        "as_of": today.isoformat(),
    }
