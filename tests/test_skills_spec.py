"""Every skill follows the Agent Skills open standard (https://agentskills.io/specification).

A local re-implementation of the ``skills-ref validate`` checks, plus the
authoring rules that keep skills portable across clients (Codex, Gemini CLI,
Cursor, Copilot, Claude Code…) — no extra dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from open_coach.guides import skills_dir, split_frontmatter

REPO = Path(__file__).resolve().parents[1]
ROOT = skills_dir()
assert ROOT is not None
SKILL_DIRS = sorted(d for d in ROOT.iterdir() if (d / "SKILL.md").is_file())

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
LINK_RE = re.compile(r"\]\((references/[^)#\s]+)\)")


def _skill(d: Path) -> tuple[dict, str]:
    return split_frontmatter((d / "SKILL.md").read_text(encoding="utf-8"))


def test_skills_found():
    assert len(SKILL_DIRS) >= 7


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda d: d.name)
def test_frontmatter_follows_spec(skill_dir: Path):
    meta, body = _skill(skill_dir)
    assert meta, "missing or unparseable YAML frontmatter"
    assert set(meta) <= ALLOWED_KEYS, f"non-standard keys: {set(meta) - ALLOWED_KEYS}"

    name = meta.get("name", "")
    assert NAME_RE.match(name), name
    assert len(name) <= 64, name
    assert name == skill_dir.name

    description = meta.get("description", "")
    assert isinstance(description, str)
    assert 1 <= len(description) <= 1024
    assert "<" not in description
    assert ">" not in description

    if "compatibility" in meta:
        assert 1 <= len(meta["compatibility"]) <= 500
    if "metadata" in meta:
        assert all(isinstance(v, str) for v in meta["metadata"].values())

    assert len(body.splitlines()) < 500, "SKILL.md body over 500 lines"


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda d: d.name)
def test_reference_links_resolve(skill_dir: Path):
    _, body = _skill(skill_dir)
    for target in LINK_RE.findall(body):
        assert (skill_dir / target).is_file(), target


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda d: d.name)
def test_every_reference_is_linked_and_long_ones_have_contents(skill_dir: Path):
    """References stay one level deep from SKILL.md; files over 100 lines carry a TOC."""
    _, body = _skill(skill_dir)
    for ref in sorted((skill_dir / "references").glob("*.md")):
        assert f"references/{ref.name}" in body, f"{ref.name} not referenced from SKILL.md"
        lines = ref.read_text(encoding="utf-8").splitlines()
        if len(lines) > 100:
            assert "## Contents" in lines, f"{ref.name}: add a '## Contents' section"


def test_claude_skills_is_a_link_to_agents_skills():
    """Single source in .agents/skills (cross-client); Claude Code reads it via the symlink."""
    link = REPO / ".claude" / "skills"
    if not link.is_symlink():
        pytest.skip("symlinks not checked out (Windows without core.symlinks)")
    assert link.resolve() == (REPO / ".agents" / "skills").resolve()
