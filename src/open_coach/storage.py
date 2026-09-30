"""Persistent storage for athlete data in ~/.open-coach/.

All data is stored as JSON files. Each top-level model carries a schema_version:
files written by an older version are upgraded by ``migrations.migrate`` on read,
saved back in the current schema, and the original is kept once as
``<file>.v<N>.bak``.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from open_coach.migrations import Kind, migrate
from open_coach.models import (
    ActivityCache,
    ActivitySummary,
    AthleteProfile,
    FeedbackLog,
    GoalsConfig,
    TrainingConstraints,
    TrainingPlan,
    WorkoutFeedback,
    WorkoutRegistry,
    WorkoutUpload,
)
from open_coach.paths import DATA_DIR, migrate_legacy_data_dir
from open_coach.plan_renderer import _slugify

DEFAULT_COACH_DIR = DATA_DIR


def _load[M: BaseModel](path: Path, kind: Kind, model: type[M]) -> M:
    """Read *path*, migrate it to the current schema, validate it as *model*.

    A migrated file is written back in the current schema; the original text is
    kept as ``<file>.v<N>.bak`` (first migration only, never overwritten).
    """
    raw = path.read_text()
    data = json.loads(raw)
    if kind == "activity_cache" and isinstance(data, list):  # legacy pre-envelope format
        data = {"schema_version": 1, "activities": data}
    data, from_version = migrate(kind, data)
    obj = model.model_validate(data)
    if from_version is not None:
        backup = path.with_name(f"{path.name}.v{from_version}.bak")
        if not backup.exists():
            backup.write_text(raw)
        path.write_text(obj.model_dump_json(indent=2))
    return obj


class CoachStorage:
    """Handles all persistence for the coaching layer."""

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            # First run after the garmin_coach → open_coach rename.
            migrate_legacy_data_dir()
        self.base_dir = base_dir or DEFAULT_COACH_DIR

    def ensure_dirs(self) -> None:
        """Create the storage directory structure."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "feedback").mkdir(exist_ok=True)
        (self.base_dir / "plans").mkdir(exist_ok=True)
        (self.base_dir / "plans" / "archive").mkdir(exist_ok=True)
        (self.base_dir / "activity_cache").mkdir(exist_ok=True)
        (self.base_dir / "workouts").mkdir(exist_ok=True)

    # ── Profile ──

    def load_profile(self) -> AthleteProfile | None:
        """Load the athlete profile, or None if never saved."""
        path = self.base_dir / "profile.json"
        if not path.exists():
            return None
        return _load(path, "profile", AthleteProfile)

    def save_profile(self, profile: AthleteProfile) -> None:
        """Persist the athlete profile (stamps updated_at)."""
        profile.updated_at = datetime.now()
        path = self.base_dir / "profile.json"
        path.write_text(profile.model_dump_json(indent=2))

    # ── Goals ──

    def load_goals(self) -> GoalsConfig | None:
        """Load the goals config, or None if never saved."""
        path = self.base_dir / "goals.json"
        if not path.exists():
            return None
        return _load(path, "goals", GoalsConfig)

    def save_goals(self, goals: GoalsConfig) -> None:
        """Persist the goals config (stamps updated_at)."""
        goals.updated_at = datetime.now()
        path = self.base_dir / "goals.json"
        path.write_text(goals.model_dump_json(indent=2))

    # ── Constraints ──

    def load_constraints(self) -> TrainingConstraints | None:
        """Load training constraints, or None if never saved."""
        path = self.base_dir / "constraints.json"
        if not path.exists():
            return None
        return TrainingConstraints.model_validate_json(path.read_text())

    def save_constraints(self, constraints: TrainingConstraints) -> None:
        """Persist training constraints (stamps updated_at)."""
        constraints.updated_at = datetime.now()
        path = self.base_dir / "constraints.json"
        path.write_text(constraints.model_dump_json(indent=2))

    # ── Feedback ──

    def _feedback_path(self, quarter: str) -> Path:
        return self.base_dir / "feedback" / f"{quarter}.json"

    @staticmethod
    def _quarter_for_date(d: datetime) -> str:
        q = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{q}"

    def load_feedback(self, quarter: str | None = None) -> FeedbackLog:
        """Load the feedback log for a quarter (default: current quarter)."""
        if quarter is None:
            quarter = self._quarter_for_date(datetime.now())
        path = self._feedback_path(quarter)
        if not path.exists():
            return FeedbackLog(period=quarter)
        return _load(path, "feedback", FeedbackLog)

    def append_feedback(self, entry: WorkoutFeedback) -> None:
        """Append one feedback entry to the current quarter's log."""
        quarter = self._quarter_for_date(datetime.now())
        log = self.load_feedback(quarter)
        log.entries.append(entry)
        path = self._feedback_path(quarter)
        path.write_text(log.model_dump_json(indent=2))

    # ── Plans ──

    def load_active_plan(self) -> TrainingPlan | None:
        """Load the active plan, or None if there is none."""
        path = self.base_dir / "plans" / "active.json"
        if not path.exists():
            return None
        return _load(path, "plan", TrainingPlan)

    def save_plan(self, plan: TrainingPlan) -> str | None:
        """Save as the active plan.

        If a *different* plan (by name) is currently active, it is archived
        first instead of being silently overwritten. Returns the name of the
        auto-archived plan, or None.
        """
        archived_name: str | None = None
        current = self.load_active_plan()
        if current is not None and current.name != plan.name:
            race_over = current.end_date < date.today()
            current.status = "completed" if race_over else "abandoned"
            self.archive_plan(current)
            archived_name = current.name

        plan.updated_at = datetime.now()
        path = self.base_dir / "plans" / "active.json"
        path.write_text(plan.model_dump_json(indent=2))
        return archived_name

    def rename_active_plan(self, new_name: str) -> tuple[str, str]:
        """Rename the active plan. Returns (old_name, new_name).

        Raises ValueError if no active plan exists.
        """
        plan = self.load_active_plan()
        if plan is None:
            raise ValueError("No active plan to rename.")
        old_name = plan.name
        plan.name = new_name
        plan.updated_at = datetime.now()
        path = self.base_dir / "plans" / "active.json"
        path.write_text(plan.model_dump_json(indent=2))
        return old_name, new_name

    def auto_archive_expired(self, grace_days: int = 3) -> TrainingPlan | None:
        """Archive the active plan if its end_date is more than grace_days past.

        The grace period leaves time to log the race result before the plan
        is filed away. Returns the archived plan, or None if nothing expired.
        """
        plan = self.load_active_plan()
        if plan is None:
            return None
        if plan.end_date + timedelta(days=grace_days) >= date.today():
            return None
        plan.status = "completed"
        self.archive_plan(plan)
        return plan

    def archive_plan(self, plan: TrainingPlan) -> None:
        """Move a plan to the archive directory."""
        archive_dir = self.base_dir / "plans" / "archive"
        safe_name = _slugify(plan.name)
        path = archive_dir / f"{safe_name}.json"
        # Never silently overwrite an existing archive: append -2, -3, ...
        suffix = 2
        while path.exists():
            path = archive_dir / f"{safe_name}-{suffix}.json"
            suffix += 1
        path.write_text(plan.model_dump_json(indent=2))

        # Remove active plan
        active_path = self.base_dir / "plans" / "active.json"
        if active_path.exists():
            active_path.unlink()

    def list_archived_plans(self) -> list[str]:
        """Sorted slugs of all archived plans."""
        archive_dir = self.base_dir / "plans" / "archive"
        if not archive_dir.exists():
            return []
        return sorted(p.stem for p in archive_dir.glob("*.json"))

    def load_archived_plan(self, name: str) -> TrainingPlan | None:
        """Load one archived plan by slug, or None if absent."""
        path = self.base_dir / "plans" / "archive" / f"{name}.json"
        if not path.exists():
            return None
        return _load(path, "plan", TrainingPlan)

    # ── Activity cache ──

    def load_activity_cache(self) -> list[ActivitySummary]:
        """Load cached activity summaries (accepts the legacy bare-list format)."""
        path = self.base_dir / "activity_cache" / "summary.json"
        if not path.exists():
            return []
        return _load(path, "activity_cache", ActivityCache).activities

    def save_activity_cache(self, activities: list[ActivitySummary]) -> None:
        """Persist activity summaries in a versioned envelope."""
        path = self.base_dir / "activity_cache" / "summary.json"
        cache = ActivityCache(activities=activities)
        path.write_text(cache.model_dump_json(indent=2))

    # ── Workout registry ──

    def load_workout_registry(self) -> WorkoutRegistry:
        """Load the upload registry (empty registry if never saved)."""
        path = self.base_dir / "workouts" / "registry.json"
        if not path.exists():
            return WorkoutRegistry()
        return WorkoutRegistry.model_validate_json(path.read_text())

    def save_workout_registry(self, registry: WorkoutRegistry) -> None:
        """Persist the upload registry."""
        path = self.base_dir / "workouts" / "registry.json"
        path.write_text(registry.model_dump_json(indent=2))

    def register_workout_upload(self, upload: WorkoutUpload) -> None:
        """Record a new watch workout upload in the registry."""
        registry = self.load_workout_registry()
        registry.workouts.append(upload)
        self.save_workout_registry(registry)

    def record_workout_schedule(
        self, workout_id: int, schedule_id: int, schedule_date: str
    ) -> None:
        """Attach a schedule (id + date) to a registered workout upload."""
        from datetime import date as date_type

        registry = self.load_workout_registry()
        entry = registry.find(workout_id)
        if entry:
            entry.schedule_ids.append(schedule_id)
            entry.schedule_dates.append(date_type.fromisoformat(schedule_date))
            self.save_workout_registry(registry)

    def mark_workout_deleted(self, workout_id: int) -> None:
        """Flag a registry entry as deleted (kept for history, skipped by cleanups)."""
        registry = self.load_workout_registry()
        entry = registry.find(workout_id)
        if entry:
            entry.deleted = True
            self.save_workout_registry(registry)
