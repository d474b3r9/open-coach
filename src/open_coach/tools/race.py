"""MCP tools for race predictions, pacing strategy, and readiness assessment.

Thin wrappers: the goal's sport plugin does the work (``Sport.race``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context

from open_coach.server import mcp
from open_coach.sports.base import SportKey
from open_coach.sports.registry import get_sport
from open_coach.tools._common import load_profile_live

if TYPE_CHECKING:
    from open_coach.models import TrainingGoal
    from open_coach.sports.base import RaceModel
    from open_coach.storage import CoachStorage


def _goal(storage: CoachStorage, goal_index: int) -> TrainingGoal | None:
    goals = storage.load_goals()
    if goals and goals.goals and goal_index < len(goals.goals):
        return goals.goals[goal_index]
    return None


def _race_model(sport: SportKey) -> RaceModel | dict:
    race = get_sport(sport).race
    if race is None:
        return {"error": f"Race tools are not available for {sport} yet."}
    return race


def _no_goal(goal_index: int) -> dict:
    return {"error": f"No goal at index {goal_index}. Set a training goal first."}


@mcp.tool(annotations={"readOnlyHint": True})
async def get_race_predictions(
    goal_index: int = 0, sport: SportKey | None = None, ctx: Context | None = None
) -> dict:
    """Predict race times with confidence intervals based on current fitness.

    Uses the sport's fitness marker (running: VDOT) and the training load
    (CTL/ATL/TSB) to predict times for the sport's standard distances plus the
    goal distance.

    Args:
        goal_index: Index of goal from goals list (default 0).
        sport: Sport to predict for (default: the goal's, else running).
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]

    profile = await load_profile_live(ctx)
    if profile is None:
        return {"error": "No athlete profile. Run onboarding first."}
    goal = _goal(storage, goal_index)
    race = _race_model(sport or (goal.sport if goal else "running"))
    if isinstance(race, dict):
        return race
    return race.predictions(profile, goal)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_pacing_strategy(
    goal_index: int = 0,
    strategy: str = "auto",
    ctx: Context | None = None,
) -> dict:
    """Generate a split-by-split pacing plan for race day.

    Args:
        goal_index: Index of goal from goals list (default 0).
        strategy: Pacing strategy — "auto" (recommended), or one of the sport's
            strategies (running: "even_split", "negative_split",
            "conservative_start", "even_effort").
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]

    profile = await load_profile_live(ctx)
    if profile is None:
        return {"error": "No athlete profile. Run onboarding first."}
    goal = _goal(storage, goal_index)
    if goal is None:
        return _no_goal(goal_index)
    race = _race_model(goal.sport)
    if isinstance(race, dict):
        return race
    return race.pacing(profile, goal, strategy)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_race_readiness(goal_index: int = 0, ctx: Context | None = None) -> dict:
    """Assess race readiness: fitness, form, training completion, and long session prep.

    Gives an overall score (0-1), component breakdown, and actionable recommendations.

    Args:
        goal_index: Index of goal from goals list (default 0).
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]

    profile = await load_profile_live(ctx)
    if profile is None:
        return {"error": "No athlete profile. Run onboarding first."}
    goal = _goal(storage, goal_index)
    if goal is None:
        return _no_goal(goal_index)
    race = _race_model(goal.sport)
    if isinstance(race, dict):
        return race

    readiness = race.readiness(profile, goal, storage.load_active_plan())
    return {
        "overall_score": round(readiness.overall_score, 2),
        "overall_status": readiness.overall_status,
        "summary": readiness.summary,
        "days_to_race": readiness.days_to_race,
        "components": [
            {
                "name": c.name,
                "score": round(c.score, 2),
                "status": c.status,
                "detail": c.detail,
            }
            for c in readiness.components
        ],
        "recommendations": readiness.recommendations,
    }
