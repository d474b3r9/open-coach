"""Tests for open_coach.plan_renderer — pure rendering + markdown file I/O."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from open_coach.models import PlannedWorkout, TrainingGoal, TrainingPlan, TrainingWeek
from open_coach.plan_renderer import (
    DEFAULT_MD_DIR,
    _resolve_md_dir,
    _slugify,
    count_phases,
    delete_plan_markdown,
    plan_markdown_path,
    render_plan_to_markdown,
    write_plan_markdown,
)
from open_coach.sports.base import Volume
from open_coach.sports.running import pace


def _make_plan(name: str = "Test 10K Plan") -> TrainingPlan:
    start = date(2026, 3, 2)  # a Monday
    weeks = [
        TrainingWeek(
            week_number=1,
            start_date=start,
            planned_volume={"running": Volume(distance_m=40000.0)},
            notes="base",
            workouts=[
                PlannedWorkout(
                    date=start,
                    workout_type="easy",
                    description="Footing tranquille",
                    target_distance_m=8000.0,
                    target_intensity=pace(330.0),
                ),
            ],
        ),
        TrainingWeek(week_number=2, start_date=date(2026, 3, 9), notes="base"),
        TrainingWeek(week_number=3, start_date=date(2026, 3, 16), notes="build"),
    ]
    return TrainingPlan(
        name=name,
        goal=TrainingGoal(
            sport="running",
            race_name="Test Race",
            distance_m=10000,
            race_date=date(2026, 4, 26),
            target_time_s=2400.0,
        ),
        start_date=start,
        end_date=date(2026, 4, 26),
        weeks=weeks,
    )


# ── render_plan_to_markdown ──────────────────────────────────────────────────


def test_render_contains_core_sections_fr() -> None:
    md = render_plan_to_markdown(_make_plan(), lang="fr")
    assert md.startswith("# Test 10K Plan\n")
    assert "## Course cible" in md
    assert "**Test Race** — 10.0 km" in md
    assert "**2026-04-26** — cible 40:00" in md  # target_time_s formatting
    assert "### Sem 1 — BASE (2026-03-02)" in md
    assert "### Sem 2 — BASE" in md
    assert "### Sem 3 — DÉVELOPPEMENT" in md  # phases shown in French
    assert "2× base" in md
    assert "1× développement" in md
    assert "| Lun 2026-03-02 | **footing** | 8.0 km | 5:30/km | Footing tranquille |" in md
    assert "- Statut : `actif`" in md
    assert "**easy**" not in md


def test_render_without_optional_fields() -> None:
    plan = _make_plan()
    plan.goal.race_date = None
    plan.goal.target_time_s = None
    md = render_plan_to_markdown(plan, lang="fr")
    assert "— cible" not in md  # no target time line suffix
    assert "Date : **?**" in md


def test_render_defaults_to_english() -> None:
    md = render_plan_to_markdown(_make_plan())
    assert md.startswith("# Test 10K Plan\n")
    assert "## Target race" in md
    assert "- Date: **2026-04-26** — target 40:00" in md
    assert "### Wk 1 — BASE (2026-03-02)" in md
    assert "km planned" in md
    assert "| ✓ | Day | Type | Distance | Target | Details |" in md
    assert "| Mon 2026-03-02 | **easy** |" in md
    assert "## Detailed plan" in md
    # English keeps the raw internal values
    assert "### Wk 3 — BUILD" in md
    assert "1× build" in md
    assert "- Status: `active`" in md


def test_write_plan_markdown_honours_language(tmp_path: Path) -> None:
    path = write_plan_markdown(_make_plan(), dest_dir=tmp_path, lang="fr")
    assert "## Course cible" in path.read_text(encoding="utf-8")


# ── count_phases / _slugify ──────────────────────────────────────────────────


def test_count_phases() -> None:
    assert count_phases(_make_plan()) == {"base": 2, "build": 1}


def test_count_phases_defaults_to_base() -> None:
    plan = _make_plan()
    plan.weeks[2].notes = None
    assert count_phases(plan) == {"base": 3}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Test 10K Plan", "test-10k-plan"),
        ("  Half -- Autumn!  ", "half-autumn"),
        ("***", "plan"),  # nothing usable → fallback slug
        ("Plan TEST 5K renommé", "plan-test-5k-renomme"),  # accents transliterated
        ("Décharge — Sem 5", "decharge-sem-5"),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert _slugify(name) == expected


# ── file I/O helpers ─────────────────────────────────────────────────────────


def test_write_plan_markdown_creates_file_at_slug_race_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "md_out"
    monkeypatch.setenv("OPEN_COACH_PLANS_MD_DIR", str(dest))
    path = write_plan_markdown(_make_plan())
    assert path == dest.resolve() / "test-10k-plan-2026-04-26.md"
    assert path.read_text(encoding="utf-8").startswith("# Test 10K Plan")


def test_write_plan_markdown_explicit_dest_dir(tmp_path: Path) -> None:
    plan = _make_plan()
    plan.goal.race_date = None
    path = write_plan_markdown(plan, dest_dir=tmp_path)
    assert path == tmp_path / "test-10k-plan-no-date.md"
    assert path.exists()


def test_plan_markdown_path_deterministic(tmp_path: Path) -> None:
    plan = _make_plan()
    p1 = plan_markdown_path(plan, dest_dir=tmp_path)
    p2 = plan_markdown_path(plan, dest_dir=tmp_path)
    assert p1 == p2 == tmp_path / "test-10k-plan-2026-04-26.md"
    # write_plan_markdown must land exactly where plan_markdown_path predicts
    assert write_plan_markdown(plan, dest_dir=tmp_path) == p1


def test_delete_plan_markdown(tmp_path: Path) -> None:
    plan = _make_plan()
    assert delete_plan_markdown(plan, dest_dir=tmp_path) is False  # nothing to delete
    path = write_plan_markdown(plan, dest_dir=tmp_path)
    assert delete_plan_markdown(plan, dest_dir=tmp_path) is True
    assert not path.exists()
    assert delete_plan_markdown(plan, dest_dir=tmp_path) is False  # idempotent


def test_resolve_md_dir_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_COACH_PLANS_MD_DIR", str(tmp_path / "override"))
    assert _resolve_md_dir() == (tmp_path / "override").resolve()


def test_resolve_md_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPEN_COACH_PLANS_MD_DIR", raising=False)
    assert _resolve_md_dir() == DEFAULT_MD_DIR
