"""MCP tools for workout upload, scheduling and calendar management.

Tools (all require a connected watch provider):
    upload_workout          — Build + upload a workout from DSL (JSON or text)
    schedule_watch_workout — Schedule an uploaded workout on a date
    delete_watch_workout   — Delete a workout template (also removes schedules)
    unschedule_watch_workout — Remove from calendar (keep template)
    list_watch_workouts    — List all templates in the watch library
    build_and_push_workout  — Upload + schedule in one call
    clean_watch_calendar   — Delete all coach-created workouts in a date range
"""

from __future__ import annotations

import logging
from datetime import date

from fastmcp import Context
from pydantic import ValidationError

from open_coach.server import mcp
from open_coach.tools._common import (
    compact_payload,
    get_watch,
    invalid_date_error,
    parse_iso_date,
    schedule_and_record,
    upload_and_register,
    watch_error,
)
from open_coach.workout_dsl import DSLWorkout, parse_dsl

logger = logging.getLogger(__name__)


def _load_dsl(workout: DSLWorkout | str, name: str | None = None) -> DSLWorkout:
    """Parse a workout given as a DSLWorkout object, DSLWorkout JSON or compact text DSL.

    Text DSL input requires a separate ``name`` (JSON embeds its own).
    Raises ``ValueError`` / ``ValidationError`` on malformed input; tools wrap
    it through :func:`_load_dsl_or_error` so they never raise to the caller.
    """
    if isinstance(workout, DSLWorkout):
        return workout
    text = workout.strip()
    if text.startswith("{"):
        return DSLWorkout.model_validate_json(text)
    if not name:
        raise ValueError("name is required when passing text DSL (non-JSON input).")
    return parse_dsl(name, text)


def _load_dsl_or_error(workout: DSLWorkout | str, name: str | None = None) -> DSLWorkout | dict:
    """Soft-failing variant of :func:`_load_dsl`: returns ``{"error": ...}`` instead of raising."""
    try:
        return _load_dsl(workout, name)
    except (ValueError, ValidationError) as exc:
        return {"error": f"Invalid workout definition: {exc}"}


# ── Upload ────────────────────────────────────────────────────────────────────


@mcp.tool()
async def upload_workout(
    workout_json: DSLWorkout | str, name: str | None = None, ctx: Context | None = None
) -> dict:
    """Build and upload a structured running workout to the watch platform.

    Args:
        workout_json: Either a DSLWorkout object (preferred) or its JSON string:
            {
              "name": "10x1min @ threshold",
              "steps": [
                {"type": "warmup",   "duration": {"seconds": 600}},
                {"type": "repeat",   "count": 10, "steps": [
                  {"type": "interval", "duration": {"seconds": 60},
                   "pace": {"min_sec_per_km": 250, "max_sec_per_km": 265}},
                  {"type": "recovery", "duration": {"seconds": 60}}
                ]},
                {"type": "cooldown", "duration": {"seconds": 600}}
              ]
            }
            ...or the compact text DSL (then `name` is required):
            WARMUP: 10min
            REPEAT: 10
              INTERVAL: 1min @ 4:10-4:25/km
              RECOVERY: 1min
            COOLDOWN: 10min
        name: Workout name — required only for text DSL input.

    Returns:
        {"workout_id": int, "name": str, "estimated_duration_s": int}
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()
    storage = ctx.lifespan_context["storage"]

    dsl = _load_dsl_or_error(workout_json, name)
    if isinstance(dsl, dict):
        return dsl
    workout_id = await upload_and_register(watch, storage, dsl)
    logger.info("Uploaded workout %r (id=%d)", dsl.name, workout_id)

    return {
        "workout_id": workout_id,
        "name": dsl.name,
        "estimated_duration_s": dsl.estimated_duration_s,
        "status": "uploaded",
    }


# ── Schedule ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def schedule_watch_workout(
    workout_id: int,
    target_date: str,
    ctx: Context | None = None,
) -> dict:
    """Schedule a workout on a specific date in the watch calendar.

    Args:
        workout_id: Workout ID returned by upload_workout.
        target_date: Date in YYYY-MM-DD format.

    Returns:
        {"schedule_id": int, "workout_id": int, "date": str}
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()
    storage = ctx.lifespan_context["storage"]

    schedule_id = await schedule_and_record(watch, storage, workout_id, target_date)
    logger.info("Scheduled workout %d on %s (schedule_id=%d)", workout_id, target_date, schedule_id)

    return {
        "schedule_id": schedule_id,
        "workout_id": workout_id,
        "date": target_date,
        "status": "scheduled",
    }


# ── Build + push in one call ──────────────────────────────────────────────────


@mcp.tool()
async def build_and_push_workout(
    workout_json: DSLWorkout | str,
    target_date: str,
    name: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Build, upload and schedule a workout in one call.

    Args:
        workout_json: DSLWorkout object (preferred), its JSON string, or the
            compact text DSL (same formats as upload_workout — text DSL requires `name`).
        target_date: Target date in YYYY-MM-DD format.
        name: Workout name — required only for text DSL input.

    Returns:
        {"workout_id": int, "schedule_id": int, "date": str, "name": str}
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()
    storage = ctx.lifespan_context["storage"]

    dsl = _load_dsl_or_error(workout_json, name)
    if isinstance(dsl, dict):
        return dsl
    if parse_iso_date(target_date) is None:
        return invalid_date_error("target_date", target_date)
    workout_id = await upload_and_register(watch, storage, dsl)
    schedule_id = await schedule_and_record(watch, storage, workout_id, target_date)

    logger.info(
        "Built & pushed workout %r (id=%d) on %s (sched=%d)",
        dsl.name,
        workout_id,
        target_date,
        schedule_id,
    )
    return {
        "workout_id": workout_id,
        "schedule_id": schedule_id,
        "date": target_date,
        "name": dsl.name,
        "estimated_duration_s": dsl.estimated_duration_s,
        "status": "uploaded_and_scheduled",
    }


# ── Delete ────────────────────────────────────────────────────────────────────


@mcp.tool(annotations={"destructiveHint": True})
async def delete_watch_workout(workout_id: int, ctx: Context | None = None) -> dict:
    """Delete a workout template from the watch library.

    This also removes all calendar schedule entries for that workout.

    Args:
        workout_id: Workout ID to delete.
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()
    storage = ctx.lifespan_context["storage"]

    await watch.delete_workout(workout_id)
    storage.mark_workout_deleted(workout_id)

    return {"workout_id": workout_id, "status": "deleted"}


@mcp.tool(annotations={"destructiveHint": True})
async def unschedule_watch_workout(schedule_id: int, ctx: Context | None = None) -> dict:
    """Remove a workout from the watch calendar without deleting the template.

    Args:
        schedule_id: Schedule ID returned by schedule_watch_workout.
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()
    await watch.unschedule_workout(schedule_id)
    return {"schedule_id": schedule_id, "status": "unscheduled"}


# ── List ──────────────────────────────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": True})
async def list_watch_workouts(
    limit: int = 100, compact: bool = True, ctx: Context | None = None
) -> dict:
    """List all workout templates in the watch library.

    Args:
        limit: Maximum number of results (default 100).
        compact: Drop empty fields and round floats (default True). Set False
            only to see the untouched vendor payload.

    Returns:
        {"workouts": [...], "count": int}
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()
    workouts = [w.raw for w in await watch.list_workouts(limit)]
    if compact:
        workouts = [compact_payload(w) for w in workouts]
    return {"workouts": workouts, "count": len(workouts)}


# ── Clean calendar ────────────────────────────────────────────────────────────


@mcp.tool(annotations={"destructiveHint": True})
async def clean_watch_calendar(
    start_date: str,
    end_date: str,
    ctx: Context | None = None,
) -> dict:
    """Delete all coach-created workouts scheduled in a date range.

    Uses the local registry to identify workouts created by this coach.
    Deletes the templates (which also removes calendar entries).

    Args:
        start_date: Start date in YYYY-MM-DD (inclusive).
        end_date: End date in YYYY-MM-DD (inclusive).

    Returns:
        {"deleted": int, "skipped": int, "errors": [...]}
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()
    storage = ctx.lifespan_context["storage"]

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    registry = storage.load_workout_registry()
    deleted = 0
    skipped = 0
    errors = []

    for entry in registry.active_workouts():
        # Check if any schedule falls in the requested range
        in_range = any(start <= d <= end for d in entry.schedule_dates)
        if not in_range:
            skipped += 1
            continue
        try:
            await watch.delete_workout(entry.workout_id)
            storage.mark_workout_deleted(entry.workout_id)
            deleted += 1
        except Exception as err:
            errors.append({"workout_id": entry.workout_id, "name": entry.name, "error": str(err)})

    return {
        "deleted": deleted,
        "skipped": skipped,
        "errors": errors,
        "status": "complete" if not errors else "partial",
    }


# ── Purge (full wipe before re-sync) ──────────────────────────────────────────


@mcp.tool(annotations={"destructiveHint": True})
async def purge_watch_workouts(
    include_unregistered: bool = False,
    ctx: Context | None = None,
) -> dict:
    """Delete coach-managed workout templates from the watch platform.

    ⚠️ DANGER: This deletes ALL workouts tracked in the local registry,
    INCLUDING workouts scheduled in the upcoming days. Designed to be used
    immediately BEFORE `sync_upcoming_workouts(weeks_ahead=N)` which re-pushes
    a fresh batch — the typical "wipe + re-sync" workflow. Calling this in
    isolation (without a follow-up sync) WILL erase your scheduled workouts
    for the coming week and leave gaps in your watch calendar.

    Watch storage limit: 25 on FR/Fenix, 40 on FR 645. Use this if you need
    to free space before re-syncing a fresh plan.

    Deleting a template also removes scheduled instances from the calendar.

    Args:
        include_unregistered: Default False = "only delete workouts created
            by this coach (registered in `~/.open-coach/workouts/registry.json`)".
            Hand-created workouts and, on Garmin, ATP plan workouts (Garmin Coach auto-plans
            like Greg McMillan / Jeff Galloway etc.) are listed but skipped.
            Set True to delete EVERY template in the library — destructive,
            use only if you really want to wipe hand-created workouts too.
            Note: ATP plan workouts cannot be deleted via API even with True
            (Garmin returns 400). To remove them, stop the active plan in
            Garmin Connect web (Plus → Coaching → end plan).

    Safer alternatives:
    - `clean_watch_calendar(start_date, end_date)` — delete only workouts
      scheduled in a specific date window. Surgical, doesn't touch templates
      outside the range.
    - `delete_watch_workout(workout_id)` — delete a single template by ID.

    Returns:
        {
          "templates_in_library": int,
          "deleted": int,
          "skipped_unregistered": int,
          "skipped_names": [str, ...],   # what was kept (for review)
          "errors": [...]
        }
    """
    assert ctx is not None
    watch = get_watch(ctx)
    if watch is None:
        return watch_error()
    storage = ctx.lifespan_context["storage"]

    library = await watch.list_workouts(200)
    registry = storage.load_workout_registry()
    registered_ids = {entry.workout_id for entry in registry.active_workouts()}

    deleted = 0
    skipped = 0
    skipped_names: list[str] = []
    errors = []

    for w in library:
        wid = w.workout_id
        name = w.name or f"workout {wid}"
        is_registered = wid in registered_ids

        if not is_registered and not include_unregistered:
            skipped += 1
            skipped_names.append(name)
            continue

        try:
            await watch.delete_workout(wid)
            if is_registered:
                storage.mark_workout_deleted(wid)
            deleted += 1
            logger.info("Purged workout %r (id=%d, registered=%s)", name, wid, is_registered)
        except Exception as err:
            errors.append({"workout_id": wid, "name": name, "error": str(err)})

    return {
        "templates_in_library": len(library),
        "deleted": deleted,
        "skipped_unregistered": skipped,
        "skipped_names": skipped_names,
        "errors": errors,
        "status": "complete" if not errors else "partial",
    }
