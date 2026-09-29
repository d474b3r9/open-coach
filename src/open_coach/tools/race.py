"""MCP tools for race predictions, pacing strategy, and readiness assessment."""

from __future__ import annotations

from fastmcp import Context

from open_coach.race_predictor import (
    assess_race_readiness,
    build_pacing_strategy,
    predict_race_times,
)
from open_coach.server import mcp
from open_coach.tools._common import load_profile_live
from open_coach.vdot import format_pace, format_time, predict_time


@mcp.tool(annotations={"readOnlyHint": True})
async def get_race_predictions(goal_index: int = 0, ctx: Context | None = None) -> dict:
    """Predict race times with confidence intervals based on current fitness.

    Uses VDOT from profile and training load (CTL/ATL/TSB) to predict times
    for standard distances (5K, 10K, Half Marathon, Marathon) plus the goal distance.

    Args:
        goal_index: Index of goal from goals list (default 0).
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]

    profile = await load_profile_live(ctx)
    if profile is None or profile.vdot is None:
        return {"error": "No VDOT available. Run onboarding or enter a race result first."}

    goals = storage.load_goals()
    target_m = None
    goal_label = None
    if goals and goals.goals and goal_index < len(goals.goals):
        goal = goals.goals[goal_index]
        target_m = goal.distance_m
        goal_label = goal.race_name

    predictions = predict_race_times(
        vdot=profile.vdot,
        ctl=profile.ctl,
        tsb=profile.tsb,
        target_distance_m=target_m,
    )

    formatted = []
    for p in predictions:
        formatted.append(
            {
                "distance": p.distance_label,
                "predicted": format_time(p.predicted_time_s),
                "range_low": format_time(p.confidence_low_s),
                "range_high": format_time(p.confidence_high_s),
                "pace": f"{format_pace(p.predicted_pace_sec_per_km)}/km",
            }
        )

    tsb_desc = "unknown"
    if profile.tsb is not None:
        tsb_desc = f"{profile.tsb:+.0f}"

    return {
        "vdot": round(profile.vdot, 1),
        "goal": goal_label,
        "fitness_context": {
            "ctl": round(profile.ctl, 1) if profile.ctl else None,
            "tsb": tsb_desc,
        },
        "predictions": formatted,
    }


@mcp.tool(annotations={"readOnlyHint": True})
async def get_pacing_strategy(
    goal_index: int = 0,
    strategy: str = "auto",
    ctx: Context | None = None,
) -> dict:
    """Generate a split-by-split pacing plan for race day.

    Args:
        goal_index: Index of goal from goals list (default 0).
        strategy: Pacing strategy — "auto" (recommended), "even_split",
                  "negative_split", "conservative_start", or "even_effort".
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]

    profile = await load_profile_live(ctx)
    if profile is None or profile.vdot is None:
        return {"error": "No VDOT available. Run onboarding or enter a race result first."}

    goals = storage.load_goals()
    if not goals or not goals.goals or goal_index >= len(goals.goals):
        return {"error": f"No goal at index {goal_index}. Set a training goal first."}

    goal = goals.goals[goal_index]

    # Use target time if set, otherwise predict from VDOT
    target_time = goal.target_time_s or predict_time(profile.vdot, goal.distance_m)

    pacing = build_pacing_strategy(goal.distance_m, target_time, strategy)

    splits_formatted = []
    for s in pacing.splits:
        splits_formatted.append(
            {
                "segment": s.split_label,
                "distance_km": s.split_km,
                "pace": f"{format_pace(s.target_pace_sec_per_km)}/km",
                "cumulative": format_time(s.cumulative_time_s),
                "note": s.effort_note,
            }
        )

    return {
        "race": goal.race_name,
        "distance": pacing.distance_label,
        "strategy": pacing.strategy_name,
        "target_time": format_time(pacing.target_time_s),
        "splits": splits_formatted,
        "key_guidance": pacing.key_guidance,
    }


@mcp.tool(annotations={"readOnlyHint": True})
async def get_race_readiness(goal_index: int = 0, ctx: Context | None = None) -> dict:
    """Assess race readiness: fitness, form, training completion, and long run prep.

    Gives an overall score (0-1), component breakdown, and actionable recommendations.

    Args:
        goal_index: Index of goal from goals list (default 0).
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]

    profile = await load_profile_live(ctx)
    if profile is None:
        return {"error": "No athlete profile. Run onboarding first."}

    goals = storage.load_goals()
    if not goals or not goals.goals or goal_index >= len(goals.goals):
        return {"error": f"No goal at index {goal_index}. Set a training goal first."}

    goal = goals.goals[goal_index]
    plan = storage.load_active_plan()

    readiness = assess_race_readiness(profile, goal, plan)

    components_formatted = []
    for c in readiness.components:
        components_formatted.append(
            {
                "name": c.name,
                "score": round(c.score, 2),
                "status": c.status,
                "detail": c.detail,
            }
        )

    return {
        "overall_score": round(readiness.overall_score, 2),
        "overall_status": readiness.overall_status,
        "summary": readiness.summary,
        "days_to_race": readiness.days_to_race,
        "components": components_formatted,
        "recommendations": readiness.recommendations,
    }
