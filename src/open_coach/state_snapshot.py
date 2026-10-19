"""Portable snapshot of the coach state, kept beside the plan markdown copies.

The coach's state (profile, goals, constraints, plans, feedback, watch upload
registry) lives in ``~/.open-coach/*.json``. The optional Drive sync only moves
the markdown in ``plans/``, so a new machine would start empty. This module
mirrors those JSON files into ``<plans dir>/.state/`` (same relative layout,
UTF-8, ``\\n`` newlines, POSIX relative paths: identical on Windows, Linux and
macOS), so the Drive sync carries them, and restores them on another machine.

Safety rules:
- A machine that never exchanged with an existing snapshot never overwrites it
  (``SYNC_MARKER`` in the data dir): it must ``restore_state`` first.
- Restore never overwrites a newer local file without ``force``; feedback and the
  watch registry are merged, archives are only added.
- No path or machine identity is stored in the snapshot.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError

from open_coach.clock import to_local, utcnow
from open_coach.jsonio import read_json_text, write_json_text
from open_coach.migrations import Kind, migrate
from open_coach.models import (
    AthleteProfile,
    FeedbackLog,
    GoalsConfig,
    TrainingConstraints,
    TrainingPlan,
    WorkoutRegistry,
)
from open_coach.paths import env
from open_coach.plan_renderer import _resolve_md_dir

logger = logging.getLogger(__name__)

SNAPSHOT_DIRNAME = ".state"
_EPOCH = datetime.min.replace(tzinfo=UTC)  # sort key for entries without a timestamp
MANIFEST_NAME = "manifest.json"
SNAPSHOT_VERSION = 1
SYNC_MARKER = ".state_sync.json"  # in the data dir: this machine has synced with a snapshot
ACTIVE_PLAN = "plans/active.json"

# Plain file names only: blocks path traversal and characters Windows forbids.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$")

_Spec = tuple[Kind | None, type[BaseModel]]
_FIXED: dict[str, _Spec] = {
    "profile.json": ("profile", AthleteProfile),
    "goals.json": ("goals", GoalsConfig),
    "constraints.json": (None, TrainingConstraints),
    "workouts/registry.json": (None, WorkoutRegistry),
    ACTIVE_PLAN: ("plan", TrainingPlan),
}
_DIRS: dict[str, _Spec] = {
    "plans/archive": ("plan", TrainingPlan),
    "feedback": ("feedback", FeedbackLog),
}


def spec_for(rel: str) -> _Spec | None:
    """Migration kind + model of a state file (POSIX relative path), None if not state."""
    if rel in _FIXED:
        return _FIXED[rel]
    path = PurePosixPath(rel)
    if str(path.parent) in _DIRS and _NAME.match(path.name):
        return _DIRS[str(path.parent)]
    return None


def snapshot_enabled() -> bool:
    """False when ``OPEN_COACH_STATE_SNAPSHOT`` is 0 / off / false / no."""
    return (env("STATE_SNAPSHOT") or "on").strip().lower() not in {"0", "off", "false", "no"}


def default_snapshot_dir() -> Path:
    """``<plans markdown dir>/.state`` (the folder the Drive sync already carries)."""
    return _resolve_md_dir() / SNAPSHOT_DIRNAME


def _files_under(root: Path) -> list[str]:
    """Relative POSIX paths of every state file below *root*."""
    rels = [rel for rel in _FIXED if (root / rel).is_file()]
    for folder in _DIRS:
        directory = root / folder
        if directory.is_dir():
            rels += sorted(
                f"{folder}/{p.name}"
                for p in directory.glob("*.json")
                if spec_for(f"{folder}/{p.name}") is not None
            )
    return rels


def _parse(rel: str, text: str) -> BaseModel:
    """Validate a state file's text against its model (after schema migration)."""
    spec = spec_for(rel)
    if spec is None:
        raise ValueError(f"not a coach state file: {rel!r}")
    kind, model = spec
    data = json.loads(text)
    if kind is not None:
        data, _ = migrate(kind, data)
    return model.model_validate(data)


def _dump(obj: BaseModel) -> str:
    return obj.model_dump_json(indent=2) + "\n"


def _normalised(path: Path) -> str:
    text = read_json_text(path)
    return text if text.endswith("\n") else text + "\n"


# ── Machine / snapshot link ──


def _has_manifest(snap: Path) -> bool:
    return (snap / MANIFEST_NAME).is_file()


def _is_synced(base: Path) -> bool:
    return (base / SYNC_MARKER).is_file()


def mirror_allowed(base: Path, snap: Path) -> bool:
    """False while an existing snapshot has not been restored (or exported) on this machine."""
    return _is_synced(base) or not _has_manifest(snap)


def _mark_synced(base: Path, via: str) -> None:
    write_json_text(
        base / SYNC_MARKER,
        json.dumps({"synced_at": utcnow().isoformat(timespec="seconds"), "via": via}) + "\n",
    )


def _write_manifest(snap: Path, files: list[str]) -> None:
    snap.mkdir(parents=True, exist_ok=True)
    manifest = {
        "snapshot_version": SNAPSHOT_VERSION,
        "exported_at": utcnow().isoformat(timespec="seconds"),
        "files": files,
    }
    write_json_text(snap / MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")


def _read_manifest(snap: Path) -> dict[str, Any]:
    try:
        data = json.loads(read_json_text(snap / MANIFEST_NAME))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ── Export (local → snapshot) ──


def _copy_to_snapshot(base: Path, snap: Path, rel: str) -> bool:
    """Copy one state file into the snapshot; True when its content changed."""
    text = _normalised(base / rel)
    dst = snap / rel
    if dst.is_file() and _normalised(dst) == text:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    write_json_text(dst, text)
    return True


def mirror_file(base: Path, snap: Path, rel: str) -> bool:
    """Best-effort mirror of one freshly written state file. Never raises."""
    try:
        if not mirror_allowed(base, snap):
            logger.warning(
                "State snapshot found at %s but never restored on this machine: not mirroring "
                "%s. Call restore_coach_state first.",
                snap,
                rel,
            )
            return False
        _copy_to_snapshot(base, snap, rel)
        if not _has_manifest(snap):
            _write_manifest(snap, _files_under(snap))
        if not _is_synced(base):
            _mark_synced(base, "export")
        return True
    except OSError as exc:
        logger.warning("Failed to mirror %s into the state snapshot: %s", rel, exc)
        return False


def mirror_remove(base: Path, snap: Path, rel: str) -> bool:
    """Best-effort removal of a state file that was deleted locally. Never raises."""
    try:
        target = snap / rel
        if mirror_allowed(base, snap) and target.is_file():
            target.unlink()
            return True
    except OSError as exc:
        logger.warning("Failed to remove %s from the state snapshot: %s", rel, exc)
    return False


def export_state(base: Path, snap: Path, force: bool = False) -> dict[str, Any]:
    """Write every local state file into the snapshot and refresh its manifest."""
    if not force and not mirror_allowed(base, snap):
        return {
            "error": (
                f"A snapshot already exists at {snap} and was never restored on this machine; "
                "exporting would overwrite it with this machine's state. Run "
                "restore_coach_state first, or pass force=true to overwrite it deliberately."
            )
        }
    changed: list[str] = []
    files = _files_under(base)
    for rel in files:
        if _copy_to_snapshot(base, snap, rel):
            changed.append(rel)
    if ACTIVE_PLAN not in files and (snap / ACTIVE_PLAN).is_file():
        (snap / ACTIVE_PLAN).unlink()  # the plan was archived since the last export
        changed.append(f"{ACTIVE_PLAN} (removed)")
    _write_manifest(snap, files)
    _mark_synced(base, "export")
    return {
        "snapshot_dir": str(snap),
        "files": files,
        "updated": changed,
        "unchanged": len(files) - len([c for c in changed if "(removed)" not in c]),
    }


# ── Restore (snapshot → local) ──


def _updated_at(obj: BaseModel) -> datetime | None:
    value = getattr(obj, "updated_at", None)
    return value if isinstance(value, datetime) else None


def _merge_feedback(local: FeedbackLog, snap: FeedbackLog) -> tuple[FeedbackLog, int]:
    seen = {e.model_dump_json() for e in local.entries}
    added = [e for e in snap.entries if e.model_dump_json() not in seen]
    merged = local.model_copy(update={"entries": [*local.entries, *added]})
    merged.entries.sort(key=lambda e: (e.date, e.recorded_at or _EPOCH))
    return merged, len(added)


def _merge_registry(local: WorkoutRegistry, snap: WorkoutRegistry) -> tuple[WorkoutRegistry, int]:
    known = {w.workout_id for w in local.workouts}
    added = [w for w in snap.workouts if w.workout_id not in known]
    return local.model_copy(update={"workouts": [*local.workouts, *added]}), len(added)


def _plan_names(root: Path) -> set[str]:
    names: set[str] = set()
    folder = root / "plans" / "archive"
    for path in folder.glob("*.json") if folder.is_dir() else []:
        try:
            plan = _parse(f"plans/archive/{path.name}", read_json_text(path))
        except (OSError, ValueError, ValidationError):
            continue
        if isinstance(plan, TrainingPlan):
            names.add(plan.name)
    return names


def _decide(
    rel: str, snap_obj: BaseModel, local_obj: BaseModel | None, force: bool, archived: set[str]
) -> tuple[str, str, BaseModel | None]:
    """(action, reason, object to write) for one file. Action: restore, merge, same, keep_local,
    skip_stale."""
    if rel == ACTIVE_PLAN and isinstance(snap_obj, TrainingPlan) and snap_obj.name in archived:
        return "skip_stale", "this plan is archived (finished or replaced)", None
    if local_obj is None:
        return "restore", "missing on this machine", snap_obj
    if local_obj.model_dump(mode="json") == snap_obj.model_dump(mode="json"):
        return "same", "identical", None
    if isinstance(local_obj, FeedbackLog) and isinstance(snap_obj, FeedbackLog):
        merged, added = _merge_feedback(local_obj, snap_obj)
        return (
            ("merge", f"{added} feedback entr{'y' if added == 1 else 'ies'} added", merged)
            if added
            else ("same", "nothing to add", None)
        )
    if isinstance(local_obj, WorkoutRegistry) and isinstance(snap_obj, WorkoutRegistry):
        merged_reg, added = _merge_registry(local_obj, snap_obj)
        return (
            ("merge", f"{added} watch upload(s) added", merged_reg)
            if added
            else ("same", "nothing to add", None)
        )
    if force:
        return "restore", "overwritten (force)", snap_obj
    snap_ts, local_ts = _updated_at(snap_obj), _updated_at(local_obj)
    if snap_ts is not None and (local_ts is None or snap_ts > local_ts):
        return "restore", f"snapshot is newer ({to_local(snap_ts):%Y-%m-%d %H:%M %Z})", snap_obj
    return "keep_local", "local file is newer or equal; force=true overwrites it", None


def restore_state(
    base: Path, snap: Path, apply: bool = False, force: bool = False
) -> dict[str, Any]:
    """Compare the snapshot with the local state, and (when *apply*) import it.

    Dry-run by default: the report lists one action per file. Files that fail
    validation are reported as ``invalid`` and never written.
    """
    if not _has_manifest(snap):
        return {
            "error": (
                f"No state snapshot at {snap}. Run the Drive sync first "
                "(bash scripts/drive_sync.sh --all) or export one from the other machine "
                "with export_coach_state."
            )
        }
    archived = _plan_names(snap) | _plan_names(base)
    actions: list[dict[str, str]] = []
    writes: list[tuple[str, BaseModel]] = []
    for rel in _files_under(snap):
        try:
            snap_obj = _parse(rel, read_json_text(snap / rel))
        except (OSError, ValueError, ValidationError) as exc:
            actions.append({"path": rel, "action": "invalid", "reason": str(exc)[:200]})
            continue
        local_obj: BaseModel | None = None
        if (base / rel).is_file():
            try:
                local_obj = _parse(rel, read_json_text(base / rel))
            except (OSError, ValueError, ValidationError):
                local_obj = None  # unreadable local file: the snapshot replaces it
        action, reason, obj = _decide(rel, snap_obj, local_obj, force, archived)
        actions.append({"path": rel, "action": action, "reason": reason})
        if obj is not None:
            writes.append((rel, obj))

    if apply:
        for rel, obj in writes:
            dst = base / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            write_json_text(dst, _dump(obj))
        _mark_synced(base, "restore")

    counts: dict[str, int] = {}
    for item in actions:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    manifest = _read_manifest(snap)
    return {
        "dry_run": not apply,
        "snapshot_dir": str(snap),
        "snapshot_exported_at": manifest.get("exported_at"),
        "actions": actions,
        "summary": counts,
    }
