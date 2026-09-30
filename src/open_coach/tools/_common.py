"""Shared helpers for MCP tool modules.

Conventions enforced here:
- Tools never raise on a missing watch provider — they return ``{"error": ...}``
  (single canonical message) so the LLM caller can react gracefully.
- ``target_date`` string parameters accept ``"today"`` or ``YYYY-MM-DD``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from open_coach.paths import env
from open_coach.plan_renderer import delete_plan_markdown
from open_coach.training_load import calculate_load_series, daily_tss_from_activities

if TYPE_CHECKING:
    from fastmcp import Context

    from open_coach.models import AthleteProfile, Language, TrainingLoadPoint, TrainingPlan
    from open_coach.providers import WatchProvider
    from open_coach.storage import CoachStorage
    from open_coach.workout_dsl import DSLWorkout

logger = logging.getLogger(__name__)


def watch_error() -> dict[str, Any]:
    """Canonical soft-failure payload when no watch provider is connected.

    The message comes from the configured provider (e.g. which credentials
    to set), so it stays accurate whatever the watch.
    """
    from open_coach.providers import not_connected_message

    return {"error": not_connected_message()}


def get_watch(ctx: Context) -> WatchProvider | None:
    """Fetch the shared watch provider from the lifespan context (None if not connected)."""
    return ctx.lifespan_context.get("watch")


def resolve_target_date(target_date: str) -> str:
    """Resolve the 'today' sentinel to an ISO date string."""
    return date.today().isoformat() if target_date == "today" else target_date


def parse_iso_date(value: str) -> date | None:
    """Parse ``YYYY-MM-DD`` (or ``"today"``) into a date; ``None`` when malformed.

    Tools use this instead of ``date.fromisoformat`` so a bad date string from
    the LLM caller becomes an ``{"error": ...}`` payload rather than a raised
    ``ValueError`` (see :func:`invalid_date_error`).
    """
    try:
        return date.fromisoformat(resolve_target_date(value.strip()))
    except (ValueError, AttributeError):
        return None


def invalid_date_error(name: str, value: str) -> dict[str, Any]:
    """Canonical soft-failure payload for a malformed date parameter."""
    return {"error": f"Invalid {name} {value!r}: expected YYYY-MM-DD."}


def profile_language(storage: CoachStorage) -> Language:
    """Output language of the athlete profile (``"en"`` when there is no profile)."""
    profile = storage.load_profile()
    return profile.language if profile is not None else "en"


def save_active_plan(storage: CoachStorage, plan: TrainingPlan) -> str | None:
    """Save *plan* as active; drop the markdown copy of a plan it auto-archives.

    ``storage.save_plan`` archives a differently named active plan. Its
    markdown copy would otherwise stay in ``plans/`` next to the new one (the
    archive JSON is the source of truth, as in ``archive_active_plan``).
    Returns the auto-archived plan name, or None.
    """
    previous = storage.load_active_plan()
    archived_name = storage.save_plan(plan)
    if archived_name is not None and previous is not None:
        try:
            delete_plan_markdown(previous)
        except OSError as exc:
            logger.warning("Failed to delete stale plan markdown: %s", exc)
    return archived_name


def compact_payload(value: Any) -> Any:
    """Shrink a raw vendor payload for the LLM without knowing its shape.

    Recursively drops ``None`` / empty strings / empty containers and rounds
    floats to 2 decimals. Vendor payloads are mostly null placeholders and
    long float tails: this keeps every real value while cutting the token
    cost, which matters for models with a small context window.
    """
    if isinstance(value, dict):
        out = {k: compact_payload(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        items = [compact_payload(v) for v in value]
        return [v for v in items if v not in (None, "", [], {})]
    if isinstance(value, float):
        return round(value, 2)
    return value


WATCH_SYNC_STEP = (
    "Sync the watch: call list_watch_workouts for every affected date (old and new), "
    "unschedule_watch_workout (and delete_watch_workout if the coach created it) for any "
    "moved or conflicting session, then push with sync_upcoming_workouts or "
    "build_and_push_workout. Push only sessions carrying quality (see the sport's rules; "
    "running: interval, tempo, race, long run with an embedded @ M block) — never a plain "
    "easy run, rest or strength session. Report what was unscheduled, pushed and left "
    "unpushed."
)


def plan_update_next_steps(*, watch_sync: bool, confirm_first: bool = False) -> list[str]:
    """Follow-up steps returned by plan-changing tools.

    These rules used to live only in agent instruction files (CLAUDE.md), which
    most MCP clients never read. Carrying them in the tool result makes every
    client see them at the moment they apply.
    """
    steps: list[str] = []
    if watch_sync:
        prefix = "Once the athlete confirms the plan: " if confirm_first else ""
        steps.append(prefix + WATCH_SYNC_STEP)
    steps.append(
        "If you can edit files: append the reason for this change to "
        "plans/training-journal.md (append-only, dated entry)."
    )
    if env("DRIVE_FOLDER_ID"):
        steps.append(
            "If you can run shell commands: run `bash scripts/drive_sync.sh --all` to refresh "
            "the Drive / Obsidian copies, and report the rclone outcome in one line."
        )
    return steps


DEFAULT_THRESHOLD_HR = 170  # used when the profile has no threshold HR
# CTL is a 42-day EWMA seeded at 0: a 90-day window still understates it by
# ~20 %, 180 days is within ~2 % of a full year (measured on a real history).
LOAD_WINDOW_DAYS = 180


class LoadSnapshot(NamedTuple):
    point: TrainingLoadPoint | None  # None when no activity carried heart-rate data
    activities_count: int
    threshold_hr: float


async def training_load_as_of(
    watch: WatchProvider, storage: CoachStorage, as_of: date, days: int = LOAD_WINDOW_DAYS
) -> LoadSnapshot:
    """CTL / ATL / TSB on *as_of*, from the last *days* of activities, every sport.

    hrTSS only needs duration and heart rate, so cycling, swimming or any other
    session loads the athlete like a run does. Rest days since the last session
    count as zero-TSS days, so the fatigue of an old session is not reported as
    current.
    """
    from datetime import timedelta

    profile = storage.load_profile()
    threshold_hr = (
        profile.threshold_hr if profile and profile.threshold_hr else DEFAULT_THRESHOLD_HR
    )
    activities = await watch.list_activities(as_of - timedelta(days=days), as_of)
    daily = daily_tss_from_activities(
        [(a.start_time_local, a.duration_s, a.avg_hr) for a in activities], threshold_hr
    )
    series = calculate_load_series(sorted(daily.items()), end_date=as_of)
    return LoadSnapshot(series[-1] if series else None, len(activities), threshold_hr)


async def load_profile_live(ctx: Context) -> AthleteProfile | None:
    """The stored profile with CTL/ATL/TSB recomputed as of today from the watch.

    The profile's own load values date from the last bootstrap. Tools that
    judge current form (race predictions, readiness, pacing, plan volume)
    use this copy; the stored profile is never rewritten. Without a watch or
    heart-rate history, the stored snapshot is returned unchanged.
    """
    storage = ctx.lifespan_context["storage"]
    profile: AthleteProfile | None = storage.load_profile()
    watch = get_watch(ctx)
    if profile is None or watch is None:
        return profile
    try:
        snapshot = await training_load_as_of(watch, storage, date.today())
    except Exception as err:
        logger.debug("Live training load failed, using the profile snapshot: %s", err)
        return profile
    if snapshot.point is None:
        return profile
    p = snapshot.point
    return profile.model_copy(update={"ctl": p.ctl, "atl": p.atl, "tsb": p.tsb})


async def upload_and_register(watch: WatchProvider, storage: CoachStorage, dsl: DSLWorkout) -> int:
    """Upload a workout to the watch platform and record it in the local registry."""
    from open_coach.models import WorkoutUpload

    workout_id = await watch.upload_workout(dsl)
    storage.register_workout_upload(
        WorkoutUpload(
            workout_id=workout_id,
            name=dsl.name,
            uploaded_at=datetime.now(),
            provider=watch.name,
        )
    )
    return workout_id


async def schedule_and_record(
    watch: WatchProvider, storage: CoachStorage, workout_id: int, iso_date: str
) -> int:
    """Schedule an uploaded workout on a date and record the schedule id."""
    schedule_id = await watch.schedule_workout(workout_id, iso_date)
    storage.record_workout_schedule(workout_id, schedule_id, iso_date)
    return schedule_id
