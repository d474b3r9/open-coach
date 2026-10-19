"""State snapshot: mirror, export, restore — including Windows <-> Linux portability."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from open_coach.models import TrainingConstraints, WorkoutFeedback
from open_coach.state_snapshot import (
    MANIFEST_NAME,
    SYNC_MARKER,
    export_state,
    mirror_allowed,
    restore_state,
    spec_for,
)
from open_coach.storage import CoachStorage
from open_coach.tools.state import export_coach_state, restore_coach_state
from tests.conftest import make_plan, mock_ctx, running_profile


def _machine(root: Path, name: str, snapshot: Path | None) -> CoachStorage:
    s = CoachStorage(base_dir=root / name, snapshot_dir=snapshot)
    s.ensure_dirs()
    return s


@pytest.fixture
def snap(tmp_path: Path) -> Path:
    return tmp_path / "plans" / ".state"


def _seed(s: CoachStorage) -> None:
    s.save_profile(running_profile(vdot=48.7, ctl=30.0, onboarding_complete=True))
    s.save_constraints(
        TrainingConstraints(notes="Tendons fragiles — pas de côtes", max_weekday_minutes=90)
    )
    s.save_plan(make_plan(name="Marathon Été", start_offset_days=-7, duration_weeks=4))


def _vdot(s: CoachStorage) -> float:
    profile = s.load_profile()
    assert profile is not None
    fitness = profile.sports["running"].fitness
    assert fitness is not None
    return fitness.value


def _actions(report: dict) -> dict[str, str]:
    return {x["path"]: x["action"] for x in report["actions"]}


def test_every_save_is_mirrored_and_marks_the_machine(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    assert (snap / "profile.json").is_file()
    assert (snap / "constraints.json").is_file()
    assert (snap / "plans" / "active.json").is_file()
    assert (snap / MANIFEST_NAME).is_file()
    assert (a.base_dir / SYNC_MARKER).is_file()


def test_archiving_removes_the_active_plan_from_the_snapshot(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    plan = make_plan(name="Old", start_offset_days=-7, duration_weeks=4)
    a.save_plan(plan)
    a.archive_plan(plan)
    assert not (snap / "plans" / "active.json").exists()
    assert (snap / "plans" / "archive" / "old.json").is_file()


def test_snapshot_files_are_utf8_lf_regardless_of_the_platform(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    raw = (snap / "constraints.json").read_bytes()
    assert b"\r" not in raw
    assert "côtes".encode() in raw  # UTF-8, not cp1252 mojibake


def test_roundtrip_to_another_machine(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    b = _machine(tmp_path, "b", None)  # fresh install, snapshot arrived through Drive
    report = restore_state(b.base_dir, snap, apply=True)
    assert report["summary"] == {"restore": 3}
    assert b.load_profile() == a.load_profile()
    constraints = b.load_constraints()
    assert constraints is not None
    assert constraints.notes == "Tendons fragiles — pas de côtes"
    plan = b.load_active_plan()
    assert plan is not None
    assert plan.name == "Marathon Été"
    assert (b.base_dir / SYNC_MARKER).is_file()


def test_dry_run_writes_nothing(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    b = _machine(tmp_path, "b", None)
    report = restore_state(b.base_dir, snap)
    assert report["dry_run"] is True
    assert b.load_profile() is None
    assert not (b.base_dir / SYNC_MARKER).exists()


def test_snapshot_with_bom_and_crlf_loads(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    path = snap / "profile.json"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes().replace(b"\n", b"\r\n"))
    b = _machine(tmp_path, "b", None)
    assert restore_state(b.base_dir, snap, apply=True)["summary"]["restore"] == 3
    assert b.load_profile() is not None


def test_new_machine_never_overwrites_an_unrestored_snapshot(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    before = (snap / "profile.json").read_text(encoding="utf-8")
    b = _machine(tmp_path, "b", snap)
    assert not mirror_allowed(b.base_dir, snap)
    b.save_profile(running_profile(vdot=40.0, ctl=5.0, onboarding_complete=True))
    assert (snap / "profile.json").read_text(encoding="utf-8") == before
    assert "error" in export_state(b.base_dir, snap)
    restore_state(b.base_dir, snap, apply=True)
    assert mirror_allowed(b.base_dir, snap)


def test_newer_local_file_is_kept_unless_forced(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    b = _machine(tmp_path, "b", None)
    restore_state(b.base_dir, snap, apply=True)
    b.save_profile(running_profile(vdot=51.0, ctl=30.0, onboarding_complete=True))
    kept = restore_state(b.base_dir, snap, apply=True)
    assert _actions(kept)["profile.json"] == "keep_local"
    assert _vdot(b) == 51.0
    forced = restore_state(b.base_dir, snap, apply=True, force=True)
    assert _actions(forced)["profile.json"] == "restore"
    assert _vdot(b) == 48.7


def test_snapshot_active_plan_that_is_archived_is_skipped(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    plan = make_plan(name="Done", start_offset_days=-30, duration_weeks=4)
    a.save_plan(plan)
    a.archive_plan(plan)
    # A stale mirror of the plan as active (e.g. from another machine) must not come back.
    (snap / "plans" / "active.json").write_text(plan.model_dump_json(), encoding="utf-8")
    b = _machine(tmp_path, "b", None)
    report = restore_state(b.base_dir, snap, apply=True)
    assert _actions(report)["plans/active.json"] == "skip_stale"
    assert b.load_active_plan() is None
    assert b.list_archived_plans() == ["done"]


def test_feedback_is_merged_not_overwritten(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    a.append_feedback(WorkoutFeedback(date=date.today(), workout_type="easy", notes="from a"))
    b = _machine(tmp_path, "b", None)
    b.append_feedback(
        WorkoutFeedback(date=date.today() - timedelta(days=1), workout_type="easy", notes="from b")
    )
    report = restore_state(b.base_dir, snap, apply=True)
    feedback = [a for p, a in _actions(report).items() if p.startswith("feedback/")]
    assert feedback == ["merge"]
    assert sorted(e.notes or "" for e in b.load_feedback().entries) == ["from a", "from b"]


def test_invalid_snapshot_file_is_reported_and_not_written(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    (snap / "goals.json").write_text("{not json", encoding="utf-8")
    b = _machine(tmp_path, "b", None)
    report = restore_state(b.base_dir, snap, apply=True)
    assert _actions(report)["goals.json"] == "invalid"
    assert b.load_goals() is None


def test_no_snapshot_gives_an_actionable_error(tmp_path: Path, snap: Path) -> None:
    b = _machine(tmp_path, "b", None)
    assert "drive_sync" in restore_state(b.base_dir, snap)["error"]


@pytest.mark.parametrize(
    "rel", ["../profile.json", "plans/archive/../../x.json", "feedback/a:b.json", "other/x.json"]
)
def test_spec_rejects_unsafe_or_foreign_paths(rel: str) -> None:
    assert spec_for(rel) is None


def test_manifest_has_no_machine_identity(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", snap)
    _seed(a)
    manifest = json.loads((snap / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert set(manifest) == {"snapshot_version", "exported_at", "files"}
    assert datetime.fromisoformat(manifest["exported_at"])


async def test_tools_export_then_restore(tmp_path: Path, snap: Path) -> None:
    a = _machine(tmp_path, "a", None)
    _seed(a)
    a.snapshot_dir = snap  # the tool exports even when auto-mirroring was off
    exported = await export_coach_state(ctx=mock_ctx(storage=a))
    assert "profile.json" in exported["files"]
    b = _machine(tmp_path, "b", snap)
    ctx = mock_ctx(storage=b)
    preview = await restore_coach_state(ctx=ctx)
    assert preview["dry_run"] is True
    assert b.load_profile() is None
    done = await restore_coach_state(apply=True, ctx=ctx)
    assert done["summary"] == {"restore": 3}
    assert any("get_coaching_context" in step for step in done["next_steps"])
    assert b.load_profile() is not None
