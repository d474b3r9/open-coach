"""One time convention: UTC stored, local shown, clock read in one place only."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from open_coach.clock import as_utc, local_today, to_local, utcnow
from open_coach.models import AthleteProfile
from open_coach.plan_renderer import render_plan_to_markdown
from open_coach.state_snapshot import restore_state
from open_coach.storage import CoachStorage
from tests.conftest import make_plan, running_profile

SRC = Path(__file__).resolve().parents[1] / "src" / "open_coach"

# The system clock is read in clock.py and nowhere else.
_FORBIDDEN = re.compile(r"\bdatetime\.(now|utcnow|today)\(|\bdate\.today\(")


def test_the_clock_is_read_only_in_clock_py() -> None:
    offenders = [
        f"{path.relative_to(SRC.parent)}:{n}: {line.strip()}"
        for path in sorted(SRC.rglob("*.py"))
        if path.name != "clock.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _FORBIDDEN.search(line) and not line.lstrip().startswith("#")
    ]
    assert not offenders, "use clock.utcnow() / clock.local_today():\n" + "\n".join(offenders)


def test_utcnow_is_aware_utc() -> None:
    now = utcnow()
    assert now.tzinfo is UTC
    assert abs(datetime.now(UTC) - now) < timedelta(seconds=5)


def test_local_today_is_the_pc_calendar_day() -> None:
    assert local_today() == to_local(utcnow()).date()


def test_naive_legacy_value_is_read_as_this_pcs_local_time() -> None:
    naive = datetime(2026, 5, 3, 18, 34, 56)
    assert as_utc(naive) == naive.astimezone(UTC)
    assert as_utc(naive).tzinfo is UTC


def test_offset_value_is_normalised_to_the_same_instant() -> None:
    paris = datetime(2026, 10, 19, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    assert as_utc(paris) == datetime(2026, 10, 19, 10, 0, tzinfo=UTC)


def test_model_serialises_as_utc_z() -> None:
    profile = AthleteProfile(created_at=datetime(2026, 10, 19, 12, 0, tzinfo=UTC))
    assert json.loads(profile.model_dump_json())["created_at"] == "2026-10-19T12:00:00Z"


def test_legacy_naive_file_loads_as_aware_utc(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    storage.ensure_dirs()
    (tmp_path / "profile.json").write_text(
        json.dumps({"schema_version": 2, "created_at": "2026-05-03T18:34:56.018748"}),
        encoding="utf-8",
    )
    profile = storage.load_profile()
    assert profile is not None
    assert profile.created_at is not None
    assert profile.created_at.tzinfo is not None
    assert profile.created_at.utcoffset() == timedelta(0)


def test_storage_stamps_utc(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    storage.ensure_dirs()
    storage.save_profile(running_profile(vdot=48.0, ctl=10.0))
    stamped = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))["updated_at"]
    assert stamped.endswith("Z")


def test_plan_markdown_shows_local_time_with_its_offset() -> None:
    plan = make_plan(start_offset_days=-7, duration_weeks=4)
    plan.updated_at = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    expected = to_local(plan.updated_at).isoformat(timespec="seconds")
    assert expected in render_plan_to_markdown(plan)


def test_restore_compares_instants_across_offsets(tmp_path: Path) -> None:
    """11:00+02:00 is 09:00Z: the 10:00Z snapshot is newer even though 11 > 10."""
    local = CoachStorage(base_dir=tmp_path / "b")
    local.ensure_dirs()
    snap = tmp_path / ".state"
    snap.mkdir()
    for root, stamp in (
        (tmp_path / "b", "2026-10-19T11:00:00+02:00"),
        (snap, "2026-10-19T10:00:00Z"),
    ):
        (root / "profile.json").write_text(
            json.dumps(
                {"schema_version": 2, "updated_at": stamp, "max_hr": 180 if root == snap else 170}
            ),
            encoding="utf-8",
        )
    (snap / "manifest.json").write_text("{}", encoding="utf-8")
    report = restore_state(local.base_dir, snap, apply=True)
    assert {x["path"]: x["action"] for x in report["actions"]}["profile.json"] == "restore"
    profile = local.load_profile()
    assert profile is not None
    assert profile.max_hr == 180
