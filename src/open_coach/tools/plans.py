"""MCP tools for training plan generation and watch calendar sync.

Tools:
    generate_training_plan  — Build a periodized plan from athlete profile + goal
    sync_upcoming_workouts  — Push next N weeks to the watch calendar (idempotent)
    update_workout_completion — Mark a planned workout as done or skipped
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastmcp import Context

from open_coach.models import TrainingConstraints
from open_coach.plan_metrics import recompute_week_actuals
from open_coach.plan_renderer import (
    count_phases,
    format_volume,
    volume_headline,
    write_plan_markdown,
)
from open_coach.server import mcp
from open_coach.sports.base import Volume
from open_coach.sports.registry import get_sport
from open_coach.tools._common import (
    get_watch,
    invalid_date_error,
    load_profile_live,
    parse_iso_date,
    plan_update_next_steps,
    profile_language,
    save_active_plan,
    schedule_and_record,
    upload_and_register,
    watch_error,
)

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _next_monday(from_date: date) -> date:
    """Return the next Monday on or after from_date."""
    days_until_monday = (7 - from_date.weekday()) % 7
    return from_date + timedelta(days=days_until_monday)


# ── Tools ──────────────────────────────────────────────────────────────────────


@mcp.tool()
async def generate_training_plan(
    start_date: str | None = None,
    goal_index: int = 0,
    ctx: Context | None = None,
) -> dict:
    """Generate a personalized training plan based on athlete profile and goals.

    Reads the athlete profile (VDOT, training pattern) and goals, then generates
    a periodized plan (base → build → peak → taper). Saves it as the active plan.

    Args:
        start_date: Plan start date (YYYY-MM-DD). Defaults to next Monday.
        goal_index: Index of goal to use from goals list (default 0 = first goal).

    Returns:
        Plan summary: name, weeks, phase breakdown, volume range.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]

    profile = await load_profile_live(ctx)
    if profile is None:
        return {"error": "No athlete profile. Run bootstrap_athlete_profile first."}

    goals = storage.load_goals()
    if not goals or not goals.goals:
        return {"error": "No training goals. Run set_training_goal first."}

    if goal_index >= len(goals.goals):
        return {"error": f"goal_index {goal_index} out of range ({len(goals.goals)} goals)."}

    goal = goals.goals[goal_index]
    if goal.race_date is None:
        return {"error": "Goal has no race_date. Update the goal with a target date."}

    constraints = storage.load_constraints() or TrainingConstraints()

    today = date.today()
    if start_date:
        parsed_start = parse_iso_date(start_date)
        if parsed_start is None:
            return invalid_date_error("start_date", start_date)
        start = parsed_start
    else:
        start = _next_monday(today)

    if goal.race_date <= start:
        return {"error": f"Race date {goal.race_date} must be after start date {start}."}

    try:
        plan = get_sport(goal.sport).generate_plan(
            goal, profile, constraints, start, profile_language(storage)
        )
    except ValueError as exc:
        return {"error": str(exc)}
    archived_name = save_active_plan(storage, plan)
    logger.info("Generated plan %r (%d weeks)", plan.name, len(plan.weeks))

    md_path: str | None = None
    try:
        md_path = str(write_plan_markdown(plan, lang=profile_language(storage)))
    except Exception as exc:
        logger.warning("Failed to write markdown copy of plan: %s", exc)

    sport = plan.goal.sport
    peak_week = max(
        plan.weeks, key=lambda w: volume_headline(sport, w.planned_volume.get(sport, Volume()))
    )

    result: dict = {
        "status": "plan_generated",
        "name": plan.name,
        "weeks": len(plan.weeks),
        "start_date": str(plan.start_date),
        "end_date": str(plan.end_date),
        "start_volume": format_volume(plan.weeks[0].planned_volume, sport),
        "peak_volume": format_volume(peak_week.planned_volume, sport),
        "phases": count_phases(plan),
        "markdown_copy": md_path,
    }
    if archived_name:
        result["auto_archived"] = archived_name
    result["next_steps"] = plan_update_next_steps(watch_sync=True, confirm_first=True)

    # Surface constraints the generator does not encode algorithmically:
    # the LLM coach adapts the plan (injuries, free-text notes).
    active_injuries = [i for i in constraints.injuries if not i.resolved]
    if active_injuries:
        result["warnings"] = [
            f"Active injury: {i.body_part} ({i.severity}) — {i.description}"
            f" (reported {i.date_reported})"
            for i in active_injuries
        ]
    if constraints.notes:
        result["constraints_notes"] = constraints.notes
    return result


@mcp.tool()
async def sync_upcoming_workouts(
    weeks_ahead: int = 2,
    include_easy: bool = False,
    ctx: Context | None = None,
) -> dict:
    """Push the next N weeks of the active plan to the watch calendar.

    By default only sessions that carry quality are pushed (tempo, intervals,
    race, long runs with an embedded pace block); plain easy / recovery / long
    runs are listed in ``left_unpushed`` — they are run on feel.

    Idempotent: dates already in the upload registry are skipped.
    Sessions whose description cannot be parsed are reported in
    ``not_converted`` (with a reason) instead of being pushed with a guessed structure.
    On HTTP 429 (rate limit), stops and returns a resume message.

    Args:
        weeks_ahead: Number of weeks ahead to sync (1-4, default 2).
        include_easy: Also push plain easy / recovery / long runs (default False).

    Returns:
        {"status": str, "uploaded": int, "skipped": int, "errors": list}
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    watch = get_watch(ctx)

    if watch is None:
        return watch_error()

    plan = storage.load_active_plan()
    if plan is None:
        return {"error": "No active plan. Run generate_training_plan first."}

    weeks_ahead = max(1, min(4, weeks_ahead))
    today = date.today()
    window_end = today + timedelta(weeks=weeks_ahead)

    to_sync = [
        workout
        for week in plan.weeks
        for workout in week.workouts
        if today <= workout.date <= window_end and not workout.completed
    ]

    if not to_sync:
        return {"status": "nothing_to_sync", "uploaded": 0, "skipped": 0}

    registry = storage.load_workout_registry()
    scheduled_dates = {d for upload in registry.active_workouts() for d in upload.schedule_dates}

    profile = storage.load_profile()

    uploaded = 0
    skipped = 0
    errors = []
    not_converted: list[dict] = []
    left_unpushed: list[dict] = []

    for workout in to_sync:
        if workout.date in scheduled_dates:
            skipped += 1
            continue
        sport = get_sport(plan.sport_of(workout))
        if not include_easy and not sport.carries_quality(workout):
            left_unpushed.append({"date": str(workout.date), "type": workout.workout_type})
            continue

        conversion = sport.workout_to_dsl(workout, profile)
        dsl = conversion.dsl
        if dsl is None:
            skipped += 1
            not_converted.append(
                {
                    "date": str(workout.date),
                    "type": workout.workout_type,
                    "description": workout.description,
                    "reason": conversion.reason,
                }
            )
            continue

        try:
            workout_id = await upload_and_register(watch, storage, dsl)
            await schedule_and_record(watch, storage, workout_id, workout.date.isoformat())

            scheduled_dates.add(workout.date)
            uploaded += 1
            logger.info("Synced %r on %s (id=%d)", dsl.name, workout.date, workout_id)

        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str or "Too Many Requests" in err_str:
                errors.append(
                    {
                        "date": str(workout.date),
                        "type": workout.workout_type,
                        "error": "rate_limited",
                    }
                )
                return {
                    "status": "rate_limited",
                    "uploaded": uploaded,
                    "skipped": skipped,
                    "errors": errors,
                    "message": (
                        f"Rate limited after {uploaded} uploads."
                        " Run sync_upcoming_workouts again in ~2 minutes."
                    ),
                }
            errors.append(
                {"date": str(workout.date), "type": workout.workout_type, "error": err_str}
            )

    result: dict = {
        "status": "complete" if not errors else "partial",
        "uploaded": uploaded,
        "skipped": skipped,
        "errors": errors,
    }
    if not_converted:
        # Sessions the parser refused to guess — push them by hand with
        # build_and_push_workout (never invent a structure).
        result["not_converted"] = not_converted
        result["hint"] = (
            "Some sessions could not be converted from their description; "
            "push them manually with build_and_push_workout."
        )
    if left_unpushed:
        # Easy runs are run on feel; include_easy=True pushes them anyway.
        result["left_unpushed"] = left_unpushed
    return result


@mcp.tool()
async def update_workout_completion(
    week_number: int,
    workout_date: str,
    completed: bool = True,
    activity_id: int | None = None,
    actual_distance_m: float | None = None,
    actual_duration_s: float | None = None,
    skipped_reason: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Mark a planned workout as completed or skipped in the active plan.

    Args:
        week_number: Week number in the plan (1-based).
        workout_date: Date of the workout (YYYY-MM-DD).
        completed: True = done, False = skipped.
        activity_id: Activity ID on the watch platform (if completed).
        actual_distance_m: Actual distance covered, in metres.
        actual_duration_s: Actual moving time, in seconds.
        skipped_reason: Reason for skipping.

    Returns:
        {"status": "updated", "week": int, "completion_rate": float}
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    plan = storage.load_active_plan()
    if plan is None:
        return {"error": "No active plan."}

    target_date = parse_iso_date(workout_date)
    if target_date is None:
        return invalid_date_error("workout_date", workout_date)
    week = next((w for w in plan.weeks if w.week_number == week_number), None)
    if week is None:
        return {"error": f"Week {week_number} not found in the plan."}

    workout = next((w for w in week.workouts if w.date == target_date), None)
    if workout is None:
        return {"error": f"No workout on {workout_date} in week {week_number}."}

    workout.completed = completed
    if activity_id is not None:
        workout.actual_activity_id = activity_id
    if actual_distance_m is not None:
        workout.actual_distance_m = actual_distance_m
    if actual_duration_s is not None:
        workout.actual_duration_s = actual_duration_s
    if skipped_reason is not None:
        workout.skipped_reason = skipped_reason

    recompute_week_actuals(week, plan.goal.sport)

    storage.save_plan(plan)

    try:
        write_plan_markdown(plan, lang=profile_language(storage))
    except Exception as exc:
        logger.warning("Failed to refresh markdown copy of plan: %s", exc)

    return {
        "status": "updated",
        "week": week_number,
        "date": workout_date,
        "completed": completed,
        "week_completion_rate": week.completion_rate,
        "next_steps": plan_update_next_steps(watch_sync=False),
    }
