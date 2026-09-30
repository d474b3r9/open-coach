"""Coaching guides: the methodology and workflow skills, readable by any MCP client.

The guides are written as Claude Code skills (``.agents/skills/<name>/SKILL.md``
plus ``references/*.md``). Claude Code loads them natively; every other client
reaches the same text through the MCP server (prompts, ``coach://guide/{name}``
resources and the ``get_coaching_guide`` tool). The markdown files stay the
single source of truth — nothing is copied into Python.

Lookup order: ``open_coach/_guides`` (bundled into the wheel by hatch), then
the repository's ``.agents/skills`` (editable / ``uv run`` installs).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import yaml

# Methodology topics → file path relative to the skills directory. The
# reference files have no frontmatter, so their catalog description lives here.
# `rules` + `principles` are universal; each sport adds `rules-<sport>` and its
# `<sport>-…` references (skill `coaching-rules-<sport>`).
METHODOLOGY_TOPICS: dict[str, str] = {
    "rules": "coaching-rules/SKILL.md",
    "principles": "coaching-rules/references/principles.md",
    "rules-running": "coaching-rules-running/SKILL.md",
    "running-methodology": "coaching-rules-running/references/methodology.md",
    "running-dsl-conventions": "coaching-rules-running/references/dsl-conventions.md",
    "running-anti-patterns": "coaching-rules-running/references/anti-patterns.md",
}
_TOPIC_DESCRIPTIONS: dict[str, str] = {
    "principles": (
        "Universal principles for every sport: 80/20 intensity split, CTL progression "
        "+5/week max, recovery week every 4."
    ),
    "running-methodology": (
        "Running: Daniels VDOT, plan structure, test placement, 10K test in a marathon "
        "block, post-race recovery, safeguards."
    ),
    "running-dsl-conventions": (
        "Running: strict rules for building a watch workout (DSL): easy run as one block, "
        "lap-button warmup and cooldown, pace window of target ±5 s, naming."
    ),
    "running-anti-patterns": (
        "Running: patterns never to apply, strength and tendon protocols, race nutrition."
    ),
}

# Workflow skills, exposed as MCP prompts of the same name.
WORKFLOWS: tuple[str, ...] = (
    "onboard",
    "plan-training",
    "push-workout",
    "analyze-run",
    "daily-check",
    "race-ready",
)

# Skills served as ``skill://<name>/…`` resources (SEP-2640). extract-transcript
# is left out: it needs a shell and only makes sense inside the repository.
SERVED_SKILLS: tuple[str, ...] = ("coaching-rules", "coaching-rules-running", *WORKFLOWS)

GuideName = Literal[
    "rules",
    "principles",
    "rules-running",
    "running-methodology",
    "running-dsl-conventions",
    "running-anti-patterns",
    "onboard",
    "plan-training",
    "push-workout",
    "analyze-run",
    "daily-check",
    "race-ready",
]

GUIDE_NAMES: tuple[str, ...] = get_args(GuideName)

_PACKAGE_DIR = Path(__file__).resolve().parent
_CANDIDATE_DIRS = (
    _PACKAGE_DIR / "_guides",
    _PACKAGE_DIR.parents[1] / ".agents" / "skills",
)


@dataclass(frozen=True)
class Guide:
    name: str
    description: str
    content: str


def skills_dir() -> Path | None:
    """First existing guides directory, or None when the guides are not shipped."""
    for candidate in _CANDIDATE_DIRS:
        if (candidate / "coaching-rules" / "SKILL.md").is_file():
            return candidate
    return None


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md into its YAML frontmatter (Agent Skills spec) and its body."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    try:
        meta = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[end + 4 :].lstrip("\n")


def load_guide(name: str) -> Guide | None:
    """Load one guide by name (methodology topic or workflow), or None if unavailable.

    A workflow guide carries its own ``references/*.md`` appended, so a client
    without file access still gets everything the skill points to.
    """
    root = skills_dir()
    if root is None:
        return None
    if name in METHODOLOGY_TOPICS:
        path = root / METHODOLOGY_TOPICS[name]
        if not path.is_file():
            return None
        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        description = _TOPIC_DESCRIPTIONS.get(name) or meta.get("description", name)
        return Guide(name, str(description), body)
    if name in WORKFLOWS:
        path = root / name / "SKILL.md"
        if not path.is_file():
            return None
        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        parts = [body.rstrip()]
        refs = root / name / "references"
        if refs.is_dir():
            for ref in sorted(refs.glob("*.md")):
                parts.append(f"## Reference: {ref.stem}\n\n{ref.read_text(encoding='utf-8')}")
        return Guide(name, str(meta.get("description", name)), "\n\n".join(parts))
    return None


def short_description(description: str) -> str:
    """Catalog form of a description: what + when, without the quoted trigger examples."""
    for marker in (' — "', ' ("'):
        cut = description.find(marker)
        if cut != -1:
            description = description[:cut]
    return description.rstrip(" .,;") + "."


def catalog() -> list[Guide]:
    """Every available guide, in GUIDE_NAMES order (tier 1 of progressive disclosure)."""
    return [g for g in (load_guide(name) for name in GUIDE_NAMES) if g is not None]


def catalog_text() -> str:
    """Compact ``- name: description`` list for tool descriptions and server instructions."""
    return "\n".join(f"- {g.name}: {short_description(g.description)}" for g in catalog())
