"""Coaching guides (Agent Skills) served to every MCP client.

Three surfaces, following the skills-over-MCP patterns (SEP-2640, skills-mcp):

- Resources ``skill://<name>/SKILL.md`` (+ ``_manifest`` and supporting files),
  through FastMCP's ``SkillProvider`` — the official Skills extension URIs.
- Prompts: one per workflow skill, for clients that turn prompts into slash commands.
- Tool ``get_coaching_guide``: the fallback for clients that only call tools.
  Its description embeds the guide catalog, which is what lets a model pick a
  guide on a natural request without being told.
"""

from __future__ import annotations

import logging

from fastmcp.prompts import Prompt
from fastmcp.server.providers.skills import SkillProvider

from open_coach.guides import (
    GUIDE_NAMES,
    SERVED_SKILLS,
    WORKFLOWS,
    GuideName,
    catalog_text,
    load_guide,
    skills_dir,
)
from open_coach.server import mcp

logger = logging.getLogger(__name__)

_UNAVAILABLE = (
    "Coaching guides are not available in this installation "
    "(expected .agents/skills/ in the repository or open_coach/_guides in the package)."
)


def register_skill_resources() -> list[str]:
    """Serve each coaching skill as ``skill://<name>/…`` resources; return their names."""
    root = skills_dir()
    if root is None:
        logger.warning("Skills directory not found — skill:// resources not registered")
        return []
    registered = []
    for name in SERVED_SKILLS:
        path = root / name
        if (path / "SKILL.md").is_file():
            mcp.add_provider(SkillProvider(path))
            registered.append(name)
    return registered


def _workflow_prompt(name: str, description: str) -> Prompt:
    def render(request: str = "") -> str:
        guide = load_guide(name)
        body = guide.content if guide else _UNAVAILABLE
        text = (
            f"Follow the `{name}` workflow below. Before any coaching decision, read the "
            'rules with get_coaching_guide("rules").\n\n' + body
        )
        if request:
            text += f"\n\n## Athlete request\n\n{request}"
        return text

    return Prompt.from_function(render, name=name, description=description)


def register_workflow_prompts() -> list[str]:
    """Register one MCP prompt per workflow skill found on disk; return their names."""
    registered = []
    for name in WORKFLOWS:
        guide = load_guide(name)
        if guide is None:
            logger.warning("Workflow guide %r not found — prompt not registered", name)
            continue
        mcp.add_prompt(_workflow_prompt(name, guide.description))
        registered.append(name)
    return registered


register_skill_resources()
register_workflow_prompts()


def _tool_description() -> str:
    catalog = catalog_text()
    head = (
        "Load a coaching guide (markdown): the methodology or a step-by-step workflow. "
        "When a request matches a guide below, load it BEFORE acting; load `rules` "
        "before any coaching decision. Same content as the skill://<name>/SKILL.md resources."
    )
    return f"{head}\n\nAvailable guides:\n{catalog}" if catalog else head


@mcp.tool(annotations={"readOnlyHint": True}, description=_tool_description())
async def get_coaching_guide(name: GuideName = "rules") -> dict:
    """Load a coaching guide by name (the catalog is in the registered description).

    Args:
        name: Guide name from the catalog in this tool's description.

    Returns:
        {"name", "description", "content"} or {"error": str}.
    """
    guide = load_guide(name)
    if guide is None:
        return {"error": _UNAVAILABLE if name in GUIDE_NAMES else f"Unknown guide {name!r}."}
    return {"name": guide.name, "description": guide.description, "content": guide.content}
