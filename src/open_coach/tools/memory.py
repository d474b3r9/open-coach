"""MCP tools and resources for persistent athlete data.

Tools (write): bootstrap, update profile, set goals/constraints, record feedback, manage plans.
Resources (read): coach://context, coach://profile, coach://goals, etc.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from pydantic import ValidationError

from open_coach.tools._common import (
    get_watch,
    injury_check,
    invalid_date_error,
    parse_iso_date,
    plan_update_next_steps,
    profile_language,
    save_active_plan,
    training_load_as_of,
    watch_error,
)

if TYPE_CHECKING:
    from open_coach.providers import WatchProvider
    from open_coach.storage import CoachStorage

from open_coach.models import (
    AthleteProfile,
    GoalsConfig,
    InjuryRecord,
    Language,
    TrainingConstraints,
    TrainingGoal,
    TrainingPlan,
    WorkoutFeedback,
)
from open_coach.onboarding import build_profile_from_activities
from open_coach.plan_renderer import delete_plan_markdown, write_plan_markdown
from open_coach.server import mcp
from open_coach.sports.base import FitnessMarker, SportKey
from open_coach.sports.registry import get_sport, is_registered

logger = logging.getLogger(__name__)

# ── MCP Resources (read-only) ──


async def _training_load_block(ctx: Context, storage: CoachStorage, today: date) -> dict:
    """CTL/ATL/TSB for the context: live from the watch, else the profile snapshot.

    The profile values are written at bootstrap and can be months old, so
    the source and date always travel with the numbers.
    """
    watch = get_watch(ctx)
    if watch is not None:
        try:
            snapshot = await training_load_as_of(watch, storage, today)
            if snapshot.point is not None:
                p = snapshot.point
                return {
                    "ctl": round(p.ctl, 1),
                    "atl": round(p.atl, 1),
                    "tsb": round(p.tsb, 1),
                    "as_of": today.isoformat(),
                    "source": "watch",
                }
        except Exception as err:
            logger.debug("Live training load failed: %s", err)
    profile = storage.load_profile()
    if profile is not None and profile.ctl is not None:
        # Bootstrap writes the load and the training pattern together; the
        # profile's updated_at moves on any save and says nothing about the load.
        pattern = next(
            (sp.training_pattern for sp in profile.sports.values() if sp.training_pattern), None
        )
        return {
            "ctl": profile.ctl,
            "atl": profile.atl,
            "tsb": profile.tsb,
            "as_of": pattern.computed_at.date().isoformat() if pattern else None,
            "source": "profile_snapshot",
            "note": "Stale snapshot from the last profile bootstrap — not today's load.",
        }
    return {"status": "unavailable"}


async def _coaching_context(ctx: Context) -> dict:
    """Consolidated coaching context: profile + fitness + goals + constraints + feedback.

    ``training_load`` is computed live from the watch history (rest days
    included); the CTL/ATL/TSB snapshot stored in the profile is left out of
    ``profile`` so it cannot be mistaken for today's load.

    Side effect (deliberate): reading this resource runs the plan lifecycle —
    an active plan whose end date is past the grace period is auto-archived
    and its markdown copy deleted.
    """
    storage = ctx.lifespan_context["storage"]

    profile = storage.load_profile()
    goals = storage.load_goals()
    constraints = storage.load_constraints()
    feedback_log = storage.load_feedback()

    auto_archived = storage.auto_archive_expired()
    if auto_archived is not None:
        with contextlib.suppress(Exception):
            delete_plan_markdown(auto_archived)
    plan = storage.load_active_plan()

    today = date.today()

    if plan:
        weeks_elapsed = (today - plan.start_date).days // 7 + 1
        days_to_end = (plan.end_date - today).days
        active_plan_info = {
            "name": plan.name,
            "status": plan.status,
            "start": str(plan.start_date),
            "end": str(plan.end_date),
            "weeks": len(plan.weeks),
            "current_week": max(1, min(weeks_elapsed, len(plan.weeks))),
            "days_remaining": max(0, days_to_end),
        }
    else:
        active_plan_info = {"status": "no_active_plan"}

    context = {
        "today": today.isoformat(),
        "day_of_week": today.strftime("%A"),
        "profile": (
            profile.model_dump(mode="json", exclude={"ctl", "atl", "tsb"})
            if profile
            else {"status": "no_profile"}
        ),
        "training_load": await _training_load_block(ctx, storage, today),
        "goals": goals.model_dump(mode="json") if goals else {"goals": []},
        "constraints": (
            constraints.model_dump(mode="json") if constraints else {"status": "not_set"}
        ),
        "recent_feedback": [e.model_dump(mode="json") for e in feedback_log.entries[-10:]],
        "active_plan": active_plan_info,
    }
    return context


@mcp.resource("coach://context")
async def get_coaching_context(ctx: Context) -> str:
    """Consolidated coaching context: profile + fitness + goals + constraints + feedback."""
    return json.dumps(await _coaching_context(ctx), default=str, indent=2)


@mcp.tool(name="get_coaching_context", annotations={"readOnlyHint": True})
async def coaching_context_tool(ctx: Context | None = None) -> dict:
    """Read the coaching context — call this FIRST in every coaching conversation.

    Returns today's date and weekday, the athlete profile (VDOT, zones, language,
    training pattern), live training load (CTL/ATL/TSB), goals, constraints
    (available days, injuries), the last 10 feedback entries and a summary of
    the active plan (current week, days remaining). Same data as the
    ``coach://context`` resource, exposed as a tool for MCP clients that do not
    read resources.

    Side effect: an active plan expired for more than 3 days is auto-archived.
    """
    assert ctx is not None
    return await _coaching_context(ctx)


@mcp.resource("coach://profile")
def get_athlete_profile(ctx: Context) -> str:
    """Full athlete profile."""
    storage: CoachStorage = ctx.lifespan_context["storage"]
    profile = storage.load_profile()
    if profile is None:
        return json.dumps({"status": "no_profile", "action": "Run bootstrap_athlete_profile tool"})
    return profile.model_dump_json(indent=2)


@mcp.resource("coach://goals")
def get_training_goals(ctx: Context) -> str:
    """Training goals."""
    storage: CoachStorage = ctx.lifespan_context["storage"]
    goals = storage.load_goals()
    return goals.model_dump_json(indent=2) if goals else json.dumps({"goals": []})


@mcp.resource("coach://constraints")
def get_constraints(ctx: Context) -> str:
    """Training constraints."""
    storage: CoachStorage = ctx.lifespan_context["storage"]
    constraints = storage.load_constraints()
    if constraints is None:
        return json.dumps({"status": "not_set"})
    return constraints.model_dump_json(indent=2)


@mcp.resource("coach://feedback/recent")
def get_recent_feedback(ctx: Context) -> str:
    """Last 20 feedback entries."""
    storage = ctx.lifespan_context["storage"]
    log = storage.load_feedback()
    recent = log.entries[-20:]
    return json.dumps([e.model_dump(mode="json") for e in recent], default=str, indent=2)


def _active_plan_payload(storage: CoachStorage) -> dict:
    """Active plan as JSON-ready dict, with today / current week / days remaining."""
    today = date.today()
    plan = storage.load_active_plan()
    if plan is None:
        return {"status": "no_active_plan", "today": today.isoformat()}
    data: dict = json.loads(plan.model_dump_json())
    data["today"] = today.isoformat()
    data["day_of_week"] = today.strftime("%A")
    weeks_elapsed = (today - plan.start_date).days // 7 + 1
    data["current_week"] = max(1, min(weeks_elapsed, len(plan.weeks)))
    data["days_remaining"] = max(0, (plan.end_date - today).days)
    return data


def _archived_plan_payload(storage: CoachStorage, name: str) -> dict:
    plan = storage.load_archived_plan(name)
    if plan is None:
        return {"error": f"No archived plan {name!r}", "available": storage.list_archived_plans()}
    return plan.model_dump(mode="json")


@mcp.resource("coach://plan/active")
def get_active_plan(ctx: Context) -> str:
    """Active training plan with current date context."""
    return json.dumps(_active_plan_payload(ctx.lifespan_context["storage"]), default=str, indent=2)


@mcp.tool(name="get_active_plan", annotations={"readOnlyHint": True})
async def active_plan_tool(ctx: Context | None = None) -> dict:
    """Read the full active training plan (every week and session).

    Adds ``today``, ``day_of_week``, ``current_week`` and ``days_remaining``.
    Same data as the ``coach://plan/active`` resource. Returns
    ``{"status": "no_active_plan"}`` when there is none.
    """
    assert ctx is not None
    return _active_plan_payload(ctx.lifespan_context["storage"])


@mcp.resource("coach://plans/archive")
def list_plan_archive(ctx: Context) -> str:
    """List of archived plans."""
    storage = ctx.lifespan_context["storage"]
    return json.dumps(storage.list_archived_plans())


@mcp.resource("coach://plans/archive/{name}")
def get_archived_plan(name: str, ctx: Context) -> str:
    """Full JSON of one archived plan (name = slug from coach://plans/archive).

    Useful to compare a previous training cycle (volumes, outcome notes,
    race result) when building a new plan.
    """
    storage: CoachStorage = ctx.lifespan_context["storage"]
    return json.dumps(_archived_plan_payload(storage, name), default=str, indent=2)


@mcp.tool(name="get_archived_plan", annotations={"readOnlyHint": True})
async def archived_plan_tool(name: str | None = None, ctx: Context | None = None) -> dict:
    """List archived plans, or read one to compare a previous training cycle.

    Args:
        name: Archived plan slug. Omit it to get the list of available slugs.

    Returns:
        {"archived_plans": [...]} without ``name``, else the full plan JSON
        (volumes, outcome notes, race result) or {"error", "available"}.
    """
    assert ctx is not None
    storage: CoachStorage = ctx.lifespan_context["storage"]
    if not name:
        return {"archived_plans": storage.list_archived_plans()}
    return _archived_plan_payload(storage, name)


# ── MCP Tools (write operations) ──


def _sports_summary(profile: AthleteProfile) -> dict:
    """Per-sport onboarding result: fitness marker and record count."""
    return {
        key: {
            "fitness": sp.fitness.model_dump() if sp.fitness else None,
            "records": len(sp.personal_records),
        }
        for key, sp in profile.sports.items()
    }


@mcp.tool()
async def bootstrap_athlete_profile(ctx: Context | None = None) -> dict:
    """Scan 6 months of watch history to build initial athlete profile.

    Detects personal records, calculates VDOT, training patterns,
    and current CTL/ATL/TSB.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    watch = get_watch(ctx)

    if watch is None:
        return watch_error()

    # Check if already complete
    existing = storage.load_profile()
    if existing and existing.onboarding_complete:
        return {"status": "already_complete", "sports": _sports_summary(existing)}

    # Fetch 6 months of activities
    from open_coach.models import ActivitySummary

    recorded = await watch.list_activities(date.today() - timedelta(days=180), date.today())
    activities = []
    for a in recorded:
        dist = a.distance_m
        dur = a.duration_s
        # A coached sport needs a distance (records, pattern); any other session with a
        # duration still loads the athlete.
        if dur > 0 and (dist > 0 or not is_registered(a.sport)):
            activities.append(
                ActivitySummary(
                    activity_id=a.activity_id or 0,
                    date=date.fromisoformat(a.start_time_local[:10]),
                    sport=a.sport,
                    distance_m=dist,
                    duration_s=dur,
                    avg_hr=round(a.avg_hr) if a.avg_hr is not None else None,
                    max_hr=round(a.max_hr) if a.max_hr is not None else None,
                    name=a.name,
                )
            )

    # Build profile (the platform's own PRs override activity-detected ones)
    platform_prs = await watch.personal_records()
    profile = await asyncio.to_thread(
        build_profile_from_activities, activities, personal_records=platform_prs
    )

    # Try to get resting HR and max HR from the watch platform
    from open_coach.zones import estimate_max_hr, estimate_resting_hr

    try:
        hr = await watch.daily_heart_rate(date.today().isoformat())
        if hr.resting_hr:
            profile.resting_hr = int(hr.resting_hr)
    except Exception as err:
        logger.debug("Resting HR fetch failed: %s", err)

    if profile.resting_hr is None:
        profile.resting_hr = estimate_resting_hr(activities)

    estimated_max = estimate_max_hr(activities)
    if estimated_max:
        profile.max_hr = estimated_max

    # Save
    storage.save_profile(profile)
    storage.save_activity_cache(activities)

    return {
        "status": "complete",
        "activities_scanned": len(activities),
        "sports": _sports_summary(profile),
        "ctl": profile.ctl,
        "atl": profile.atl,
        "tsb": profile.tsb,
        "resting_hr": profile.resting_hr,
        "max_hr": profile.max_hr,
    }


@mcp.tool()
async def update_athlete_profile(
    max_hr: int | None = None,
    resting_hr: int | None = None,
    threshold_hr: int | None = None,
    weight_kg: float | None = None,
    fitness_override: float | None = None,
    sport: SportKey = "running",
    language: Language | None = None,
    ctx: Context | None = None,
) -> dict:
    """Update athlete profile fields. Only provided fields are changed.

    ``fitness_override`` sets the headline fitness number of ``sport`` by hand
    (running: VDOT); every other field is shared by all sports.

    ``language`` (``"en"`` | ``"fr"``) selects the language of text the coach
    generates itself: plan markdown copies and session descriptions.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    profile = storage.load_profile() or AthleteProfile()

    if max_hr is not None:
        profile.max_hr = max_hr
    if resting_hr is not None:
        profile.resting_hr = resting_hr
    if threshold_hr is not None:
        profile.threshold_hr = threshold_hr
    if weight_kg is not None:
        profile.weight_kg = weight_kg
    if fitness_override is not None:
        profile.sport_profile(sport, create=True).fitness = FitnessMarker(
            metric=get_sport(sport).fitness_metric, value=fitness_override, source="manual override"
        )
    if language is not None:
        profile.language = language

    storage.save_profile(profile)
    return {"status": "updated", "profile": profile.model_dump(mode="json")}


@mcp.tool()
async def set_training_goal(
    race_name: str,
    distance_m: float,
    race_date: str | None = None,
    sport: SportKey = "running",
    target_time_s: float | None = None,
    priority: Literal["A", "B", "C"] = "A",
    ctx: Context | None = None,
) -> dict:
    """Set or add a training goal."""
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    parsed_race_date: date | None = None
    if race_date:
        parsed_race_date = parse_iso_date(race_date)
        if parsed_race_date is None:
            return invalid_date_error("race_date", race_date)

    goals = storage.load_goals() or GoalsConfig()

    goal = TrainingGoal(
        sport=sport,
        race_name=race_name,
        distance_m=distance_m,
        race_date=parsed_race_date,
        target_time_s=target_time_s,
        priority=priority,
        created_at=datetime.now(),
    )
    goals.goals.append(goal)
    storage.save_goals(goals)

    return {"status": "goal_added", "goals_count": len(goals.goals)}


@mcp.tool()
async def set_training_constraints(
    available_days: list[str] | None = None,
    max_sessions_per_week: int | None = None,
    max_weekday_minutes: int | None = None,
    max_weekend_minutes: int | None = None,
    max_minutes_by_day: dict[str, int] | None = None,
    notes: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Set training constraints. Only provided fields are changed.

    Duration caps are enforced by generate_training_plan: ``max_minutes_by_day``
    (e.g. ``{"monday": 45}``) wins over ``max_weekday_minutes`` /
    ``max_weekend_minutes`` for that day, and a day capped under 60 minutes gets
    an easy session rather than the long run or a quality session. Notes are
    surfaced in the plan response for the coach.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    constraints = storage.load_constraints() or TrainingConstraints()

    if available_days is not None:
        constraints.available_days = available_days
    if max_sessions_per_week is not None:
        constraints.max_sessions_per_week = max_sessions_per_week
    if max_weekday_minutes is not None:
        constraints.max_weekday_minutes = max_weekday_minutes
    if max_weekend_minutes is not None:
        constraints.max_weekend_minutes = max_weekend_minutes
    if max_minutes_by_day is not None:
        try:
            constraints.max_minutes_by_day = TrainingConstraints.model_validate(
                {"max_minutes_by_day": max_minutes_by_day}
            ).max_minutes_by_day
        except ValidationError as exc:
            return {"error": f"Invalid max_minutes_by_day: {exc.errors()[0]['msg']}"}
    if notes is not None:
        constraints.notes = notes

    storage.save_constraints(constraints)
    return {"status": "constraints_updated"}


@mcp.tool()
async def report_injury(
    description: str,
    body_part: str,
    severity: Literal["minor", "moderate", "severe"] = "minor",
    ctx: Context | None = None,
) -> dict:
    """Record an injury that should influence training recommendations."""
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    constraints = storage.load_constraints() or TrainingConstraints()

    injury = InjuryRecord(
        description=description,
        body_part=body_part,
        severity=severity,
        date_reported=date.today(),
    )
    constraints.injuries.append(injury)
    storage.save_constraints(constraints)

    return {"status": "injury_recorded", "total_injuries": len(constraints.injuries)}


@mcp.tool()
async def resolve_injury(body_part: str, ctx: Context | None = None) -> dict:
    """Mark all unresolved injuries for a body part as resolved (today).

    Args:
        body_part: Body part as recorded by report_injury (case-insensitive).
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    constraints = storage.load_constraints() or TrainingConstraints()

    resolved_count = 0
    for injury in constraints.injuries:
        if not injury.resolved and injury.body_part.lower() == body_part.lower():
            injury.resolved = True
            injury.resolved_date = date.today()
            resolved_count += 1

    if resolved_count == 0:
        open_parts = sorted({i.body_part for i in constraints.injuries if not i.resolved})
        return {"error": f"No unresolved injury for {body_part!r}.", "open_injuries": open_parts}

    storage.save_constraints(constraints)
    return {"status": "injury_resolved", "resolved_count": resolved_count}


@mcp.tool()
async def record_workout_feedback(
    activity_id: int | None = None,
    feedback_date: str | None = None,
    workout_type: str | None = None,
    perceived_effort: Literal["too_easy", "easy", "moderate", "hard", "too_hard"] | None = None,
    feeling: Literal["great", "good", "okay", "tired", "terrible"] | None = None,
    notes: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Record subjective feedback for a workout.

    If activity_id is provided, objective data is auto-filled from the watch platform.
    If the active plan has a workout on the same date, its targets
    (sport, distance, intensity, type) are auto-filled for planned-vs-actual
    tracking; ``workout_type`` defaults to the planned one, else ``easy``.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]

    entry_date = parse_iso_date(feedback_date) if feedback_date else date.today()
    if entry_date is None:
        return invalid_date_error("feedback_date", feedback_date or "")

    plan = storage.load_active_plan()
    planned = (
        next((w for week in plan.weeks for w in week.workouts if w.date == entry_date), None)
        if plan
        else None
    )

    entry = WorkoutFeedback(
        activity_id=activity_id,
        date=entry_date,
        sport=plan.sport_of(planned) if plan and planned else None,
        workout_type=workout_type or (planned.workout_type if planned else "easy"),
        perceived_effort=perceived_effort,
        feeling=feeling,
        notes=notes,
        recorded_at=datetime.now(),
    )

    # Auto-fill from the watch platform if connected and activity_id provided
    if activity_id:
        watch = get_watch(ctx)
        if watch:
            try:
                detail = await watch.activity_detail(activity_id)
                entry.actual_distance_m = detail.distance_m
                entry.actual_duration_s = detail.duration_s
                entry.avg_hr = round(detail.avg_hr) if detail.avg_hr is not None else None
                if is_registered(detail.sport):
                    entry.actual_intensity = get_sport(detail.sport).activity_intensity(
                        detail.distance_m, detail.duration_s
                    )
            except Exception as err:
                logger.debug("Activity detail fetch failed for %s: %s", activity_id, err)

    # Planned targets from the active plan (same date)
    if planned:
        entry.planned_distance_m = planned.target_distance_m
        entry.planned_intensity = planned.target_intensity

    storage.append_feedback(entry)
    return {
        "status": "feedback_recorded",
        "entry": entry.model_dump(mode="json"),
        **injury_check(storage),
    }


@mcp.tool()
async def save_training_plan(plan_json: TrainingPlan | str, ctx: Context | None = None) -> dict:
    """Save a training plan as the active plan (replaces the current one).

    Typical edit loop: get_active_plan → modify the weeks/sessions → pass the
    whole plan back here. A differently named active plan is auto-archived.

    Args:
        plan_json: The full training plan, as an object matching the schema
            (preferred) or as a JSON string of that object.

    Returns:
        {"status": "plan_saved", "name", "weeks", "next_steps": [...]} — follow
        ``next_steps`` (watch sync, journal) right away.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    if isinstance(plan_json, TrainingPlan):
        plan = plan_json
    else:
        try:
            plan = TrainingPlan.model_validate_json(plan_json)
        except ValidationError as exc:
            return {"error": f"Invalid plan_json: {exc.error_count()} validation error(s): {exc}"}
    archived_name = save_active_plan(storage, plan)
    result: dict = {"status": "plan_saved", "name": plan.name, "weeks": len(plan.weeks)}
    if archived_name:
        result["auto_archived"] = archived_name
    result["next_steps"] = plan_update_next_steps(watch_sync=True)
    # Keep the markdown copy in sync — same contract as generate_training_plan
    # and update_workout_completion: JSON is the source of truth, md failure is soft.
    try:
        result["markdown_path"] = str(write_plan_markdown(plan, lang=profile_language(storage)))
    except Exception as exc:
        logger.warning("Failed to refresh markdown copy of plan: %s", exc)
    return result


@mcp.tool()
async def rename_active_plan(new_name: str, ctx: Context | None = None) -> dict:
    """Rename the active plan and refresh its markdown copy.

    The stale markdown copy (old slug) is deleted, a new one is written.

    Args:
        new_name: New plan name.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    plan = storage.load_active_plan()
    if plan is None:
        return {"error": "No active plan to rename."}

    delete_plan_markdown(plan)
    old_name, _ = storage.rename_active_plan(new_name)
    renamed = storage.load_active_plan()
    md_path: str | None = None
    if renamed is not None:
        try:
            md_path = str(write_plan_markdown(renamed, lang=profile_language(storage)))
        except Exception as err:
            logger.warning("Markdown copy failed after rename: %s", err)

    return {
        "status": "plan_renamed",
        "old_name": old_name,
        "new_name": new_name,
        "markdown_copy": md_path,
    }


@mcp.tool(annotations={"destructiveHint": True})
async def archive_active_plan(
    outcome_notes: str | None = None,
    race_result_s: float | None = None,
    status: Literal["completed", "abandoned"] = "completed",
    cleanup_watch: bool = True,
    ctx: Context | None = None,
) -> dict:
    """Archive the active plan (completed or abandoned) with results.

    Also deletes the auto-generated markdown copy (the archive JSON is the
    source of truth) and, unless cleanup_watch is False, removes the plan's
    future coach-created workouts from the watch calendar.

    Args:
        outcome_notes: Free-text outcome summary.
        race_result_s: Race result in seconds, if raced.
        status: "completed" (default) or "abandoned".
        cleanup_watch: Delete future registered watch workouts (default True).
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    plan = storage.load_active_plan()

    if plan is None:
        return {"error": "No active plan to archive."}

    plan.status = status
    plan.outcome_notes = outcome_notes
    plan.race_result_s = race_result_s
    storage.archive_plan(plan)

    with contextlib.suppress(Exception):
        delete_plan_markdown(plan)

    watch_cleanup: dict | None = None
    watch = get_watch(ctx)
    if cleanup_watch and watch is not None:
        watch_cleanup = await _cleanup_future_watch_workouts(watch, storage)

    result: dict = {"status": "plan_archived", "name": plan.name, "plan_status": status}
    if watch_cleanup is not None:
        result["watch_cleanup"] = watch_cleanup
    return result


async def _cleanup_future_watch_workouts(watch: WatchProvider, storage: CoachStorage) -> dict:
    """Delete coach-created watch workouts scheduled strictly after today."""
    registry = storage.load_workout_registry()
    today = date.today()
    deleted = 0
    errors: list[dict] = []
    for entry in registry.active_workouts():
        if not any(d > today for d in entry.schedule_dates):
            continue
        try:
            await watch.delete_workout(entry.workout_id)
            storage.mark_workout_deleted(entry.workout_id)
            deleted += 1
        except Exception as err:
            errors.append({"workout_id": entry.workout_id, "error": str(err)})
    return {"deleted": deleted, "errors": errors}
