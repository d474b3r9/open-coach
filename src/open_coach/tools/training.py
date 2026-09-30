"""MCP tools for fitness from a race, training zones (per sport) and training load."""

from __future__ import annotations

from datetime import date

from fastmcp import Context

from open_coach.server import mcp
from open_coach.sports.base import SportKey
from open_coach.sports.registry import get_sport
from open_coach.tools._common import (
    LOAD_WINDOW_DAYS,
    get_watch,
    training_load_as_of,
    watch_error,
)
from open_coach.training_load import interpret_tsb


@mcp.tool(annotations={"readOnlyHint": True})
async def calculate_fitness_from_race(
    distance_meters: float, time_seconds: float, sport: SportKey = "running"
) -> dict:
    """Fitness marker of a sport from a race result or time trial, with its training targets.

    Running: VDOT (Daniels), training paces and race predictions.

    Args:
        distance_meters: Race distance in meters (e.g. 5000, 10000, 21097.5, 42195).
        time_seconds: Finish time in seconds.
        sport: Sport of the result (default running).
    """
    plugin = get_sport(sport)
    fitness = plugin.fitness_from_race(distance_meters, time_seconds)
    return {
        "sport": sport,
        "fitness": fitness.model_dump(),
        **plugin.describe_fitness(fitness.value),
    }


@mcp.tool(annotations={"readOnlyHint": True})
async def get_training_zones(
    sport: SportKey = "running",
    fitness: float | None = None,
    race_distance_m: float | None = None,
    race_time_s: float | None = None,
    ctx: Context | None = None,
) -> dict:
    """Training zones of a sport (running: Daniels pace zones + Karvonen HR).

    The fitness marker (running: VDOT) comes from ``fitness``, else from a race
    result (``race_distance_m`` + ``race_time_s``), else from the profile.

    Args:
        sport: Sport of the zones (default running).
        fitness: Fitness marker value (running: VDOT), if known.
        race_distance_m: Race distance in meters (alternative to fitness).
        race_time_s: Race time in seconds (alternative to fitness).
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    profile = storage.load_profile()
    plugin = get_sport(sport)

    if fitness is None:
        if race_distance_m and race_time_s:
            fitness = plugin.fitness_from_race(race_distance_m, race_time_s).value
        elif profile is not None and (marker := profile.sport_profile(sport).fitness):
            fitness = marker.value
        else:
            return {
                "error": f"No {sport} fitness available. Provide race data or run onboarding first."
            }

    return plugin.training_zones(profile, fitness)


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
        "activities_count": snapshot.activities_count,
        "as_of": today.isoformat(),
    }
