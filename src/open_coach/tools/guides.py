"""MCP prompts, resources and tool exposing the coaching guides to every client.

- Prompts: one per workflow skill (``onboard``, ``plan-training``…), for
  clients that surface MCP prompts as slash commands.
- Resource template ``coach://guide/{name}``: any guide as markdown.
- Tool ``get_coaching_guide``: the same text, for clients that only call tools.
"""

from __future__ import annotations

import logging

from fastmcp.prompts import Prompt

from open_coach.guides import GUIDE_NAMES, WORKFLOWS, GuideName, load_guide
from open_coach.server import mcp

logger = logging.getLogger(__name__)

_UNAVAILABLE = (
    "Coaching guides are not available in this installation "
    "(expected .claude/skills/ in the repository or open_coach/_guides in the package)."
)


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


register_workflow_prompts()


@mcp.resource("coach://guide/{name}", mime_type="text/markdown")
def get_guide_resource(name: str) -> str:
    """Coaching guide as markdown: rules, methodology, dsl-conventions, anti-patterns,
    or a workflow (onboard, plan-training, push-workout, analyze-run, daily-check, race-ready).
    """
    guide = load_guide(name)
    if guide is None:
        return f"Unknown guide {name!r}. Available: {', '.join(GUIDE_NAMES)}."
    return guide.content


@mcp.tool(annotations={"readOnlyHint": True})
async def get_coaching_guide(name: GuideName = "rules") -> dict:
    """Read the coaching methodology or a step-by-step workflow (markdown).

    Call ``rules`` before any coaching decision (plan, session, pace, recovery
    advice); it points to the detailed topics. Load the matching workflow
    before acting on a request.

    Args:
        name: Methodology — ``rules`` (entry point), ``methodology`` (Daniels,
            80/20, periodization, recovery), ``dsl-conventions`` (how to build
            a watch workout), ``anti-patterns``. Workflows — ``onboard``,
            ``plan-training``, ``push-workout``, ``analyze-run``,
            ``daily-check``, ``race-ready``.

    Returns:
        {"name", "description", "content"} or {"error": str}.
    """
    guide = load_guide(name)
    if guide is None:
        return {"error": _UNAVAILABLE if name in GUIDE_NAMES else f"Unknown guide {name!r}."}
    return {"name": guide.name, "description": guide.description, "content": guide.content}
