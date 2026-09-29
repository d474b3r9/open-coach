"""MCP tools for recovery monitoring and adaptive training recommendations."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from fastmcp import Context

from open_coach.recovery_monitor import assess_recovery, recommend_adaptation
from open_coach.server import mcp
from open_coach.tools._common import get_watch, resolve_target_date, training_load_as_of

if TYPE_CHECKING:
    from open_coach.providers import WatchProvider
    from open_coach.storage import CoachStorage

logger = logging.getLogger(__name__)


async def _fetch_recovery_data(
    watch: WatchProvider | None, storage: CoachStorage, target_date: str
) -> dict:
    """Fetch all raw data needed for recovery assessment.

    Returns a dict with keys matching assess_recovery() parameters.
    """
    d = resolve_target_date(target_date)

    data: dict = {
        "hrv_last_night": None,
        "hrv_weekly_avg": None,
        "sleep_score": None,
        "sleep_duration_s": None,
        "tsb": None,
        "avg_stress": None,
        "recent_feedback": None,
        # Assess the requested day, not the day the tool runs.
        "today": date.fromisoformat(d),
    }

    # Fetch from the watch platform (graceful on failure)
    if watch is not None:
        data.update((await watch.recovery_signals(d)).model_dump())

    # TSB on the assessed day, from the watch history (rest days included);
    # the profile snapshot (last bootstrap) is only a fallback.
    if watch is not None:
        try:
            snapshot = await training_load_as_of(watch, storage, data["today"])
            if snapshot.point is not None:
                data["tsb"] = snapshot.point.tsb
        except Exception as err:
            logger.debug("Training load fetch failed: %s", err)
    if data["tsb"] is None:
        profile = storage.load_profile()
        if profile:
            data["tsb"] = profile.tsb

    # Recent feedback (last 3 entries) — load_feedback() defaults to the current quarter
    try:
        feedback_log = storage.load_feedback()
        if feedback_log and feedback_log.entries:
            data["recent_feedback"] = feedback_log.entries[-3:]
    except Exception as err:
        logger.debug("Feedback load failed: %s", err)

    return data


@mcp.tool(annotations={"readOnlyHint": True})
async def get_recovery_status(target_date: str = "today", ctx: Context | None = None) -> dict:
    """Assess current recovery from HRV, sleep, TSB, stress, and subjective feedback.

    Returns an overall score (0-100), status (green/yellow/red), signal breakdown,
    and actionable recommendations.

    Args:
        target_date: Date string (YYYY-MM-DD) or "today" (default).
    """
    assert ctx is not None
    watch = get_watch(ctx)
    storage = ctx.lifespan_context["storage"]

    data = await _fetch_recovery_data(watch, storage, target_date)
    assessment = assess_recovery(**data)

    signals_formatted = []
    for s in assessment.signals:
        signals_formatted.append(
            {
                "name": s.name,
                "score": round(s.score, 2),
                "status": s.status,
                "value": s.value,
                "detail": s.detail,
                "available": s.available,
            }
        )

    return {
        "date": str(assessment.date),
        "overall_score": round(assessment.overall_score, 1),
        "status": assessment.status,
        "signals": signals_formatted,
        "summary": assessment.summary,
        "recommendations": assessment.recommendations,
    }


@mcp.tool(annotations={"readOnlyHint": True})
async def get_adaptive_recommendation(
    target_date: str = "today", ctx: Context | None = None
) -> dict:
    """Get a concrete workout recommendation based on recovery and today's plan.

    Combines recovery assessment with the active training plan to recommend:
    proceed, reduce intensity, reduce volume, swap to easy, or rest day.

    Args:
        target_date: Date string (YYYY-MM-DD) or "today" (default).
    """
    assert ctx is not None
    watch = get_watch(ctx)
    storage = ctx.lifespan_context["storage"]

    data = await _fetch_recovery_data(watch, storage, target_date)
    assessment = assess_recovery(**data)

    # Find today's planned workout
    target = date.fromisoformat(target_date) if target_date != "today" else date.today()
    planned_workout = None
    plan = storage.load_active_plan()
    if plan:
        for week in plan.weeks:
            for w in week.workouts:
                if w.date == target and not w.completed:
                    planned_workout = w
                    break
            if planned_workout:
                break

    profile = storage.load_profile()
    rec = recommend_adaptation(assessment, planned_workout, profile)

    result: dict[str, Any] = {
        "recovery": {
            "score": round(assessment.overall_score, 1),
            "status": assessment.status,
            "summary": assessment.summary,
        },
        "recommendation": {
            "action": rec.action,
            "reasoning": rec.reasoning,
        },
    }

    if planned_workout:
        result["planned_workout"] = {
            "date": str(planned_workout.date),
            "type": planned_workout.workout_type,
            "description": planned_workout.description,
        }

    if rec.original_workout:
        result["recommendation"]["original_workout"] = rec.original_workout
    if rec.adjusted_workout:
        result["recommendation"]["adjusted_workout"] = rec.adjusted_workout
    if rec.intensity_reduction_pct is not None:
        result["recommendation"]["intensity_reduction_pct"] = rec.intensity_reduction_pct

    result["recommendation"]["recommendations"] = assessment.recommendations

    return result
