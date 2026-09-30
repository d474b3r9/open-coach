"""Guards for running the coach from any MCP client, not only Claude Code.

Operating rules, workflows and methodology must reach clients that never read
CLAUDE.md or load skills: through the server instructions (with the guide
catalog), MCP prompts, ``skill://`` resources (SEP-2640), the catalog in the
``get_coaching_guide`` description, and tools mirroring ``coach://`` resources.
"""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from open_coach.guides import (
    GUIDE_NAMES,
    METHODOLOGY_TOPICS,
    SERVED_SKILLS,
    WORKFLOWS,
    load_guide,
    short_description,
    skills_dir,
)
from open_coach.models import TrainingPlan
from open_coach.server import mcp
from open_coach.tools._common import compact_payload, plan_update_next_steps
from open_coach.tools.guides import get_coaching_guide
from open_coach.tools.memory import (
    active_plan_tool,
    archived_plan_tool,
    coaching_context_tool,
    get_coaching_context,
)
from open_coach.workout_dsl import DSLWorkout
from tests.conftest import MockStorage, make_plan, mock_ctx

# ── Guides ────────────────────────────────────────────────────────────────────


def test_guide_names_cover_topics_and_workflows():
    assert set(GUIDE_NAMES) == set(METHODOLOGY_TOPICS) | set(WORKFLOWS)


def test_every_workflow_skill_on_disk_is_exposed():
    """A new .agents/skills/<workflow>/ must be added to WORKFLOWS (and GuideName)."""
    root = skills_dir()
    assert root is not None
    on_disk = {
        d.name for d in root.iterdir() if (d / "SKILL.md").is_file() and d.name != "coaching-rules"
    }
    # extract-transcript is a repo maintenance skill (needs a shell), not a coaching workflow.
    assert on_disk - {"extract-transcript"} == set(WORKFLOWS)


def test_every_guide_loads_without_frontmatter():
    for name in GUIDE_NAMES:
        guide = load_guide(name)
        assert guide is not None, name
        assert guide.content.strip()
        assert not guide.content.startswith("---"), name
        assert guide.description


def test_workflow_guide_includes_its_references():
    guide = load_guide("push-workout")
    assert guide is not None
    assert "## Reference: conventions" in guide.content


def test_workflow_skills_do_not_depend_on_resources_only():
    """Workflows must name the tool mirror, not a bare coach:// resource read."""
    for name in WORKFLOWS:
        guide = load_guide(name)
        assert guide is not None
        assert "Read `coach://" not in guide.content, name


async def test_get_coaching_guide_tool():
    result = await get_coaching_guide("rules")
    assert result["name"] == "rules"
    assert "Daniels" in result["content"] or "VDOT" in result["content"]


async def test_prompts_registered_for_every_workflow():
    prompts = {p.name for p in await mcp.list_prompts()}
    assert prompts == set(WORKFLOWS)


async def test_prompt_renders_workflow_and_request():
    prompt = await mcp.get_prompt("daily-check")
    assert prompt is not None
    rendered = await prompt.render({"request": "tired today"})
    text = rendered.messages[0].content.text  # type: ignore[union-attr]
    assert "get_recovery_status" in text
    assert "tired today" in text


async def test_skills_served_as_skill_resources():
    """SEP-2640 URIs: skill://<name>/SKILL.md, plus supporting files through a template."""
    uris = {str(r.uri) for r in await mcp.list_resources()}
    for name in SERVED_SKILLS:
        assert f"skill://{name}/SKILL.md" in uris, name
    assert "skill://extract-transcript/SKILL.md" not in uris
    result = await mcp.read_resource("skill://coaching-rules/references/methodology.md")
    assert "Daniels" in str(result)


async def test_tool_description_embeds_the_catalog():
    """skills-mcp pattern: the catalog in an always-loaded tool description."""
    tool = await mcp.get_tool("get_coaching_guide")
    assert tool is not None
    assert tool.description
    for name in GUIDE_NAMES:
        assert f"- {name}: " in tool.description, name


def test_short_description_drops_trigger_examples():
    desc = 'Does X. Use when the user asks for X — "do x", "fais x".'
    assert short_description(desc) == "Does X. Use when the user asks for X."


# ── Server instructions ───────────────────────────────────────────────────────


def test_instructions_carry_the_operating_rules():
    text = mcp.instructions or ""
    for needle in (
        "get_coaching_context",
        "get_coaching_guide",
        "next_steps",
        "list_watch_workouts",
        "never a plain easy run",
        "orphan",
        "raw watch name",
        "language",
        "skill://",
    ):
        assert needle in text, needle
    for name in GUIDE_NAMES:
        assert f"- {name}: " in text, name


# ── Resource mirrors ──────────────────────────────────────────────────────────


async def test_context_tool_matches_resource():
    storage = MockStorage(plan=make_plan(start_offset_days=-7))
    tool_data = await coaching_context_tool(ctx=mock_ctx(storage))
    resource_data = json.loads(await get_coaching_context(mock_ctx(storage)))
    assert json.loads(json.dumps(tool_data, default=str)) == resource_data


async def test_active_plan_tool():
    ctx = mock_ctx(MockStorage(plan=make_plan(start_offset_days=-7)))
    data = await active_plan_tool(ctx=ctx)
    assert data["current_week"] == 2
    assert "weeks" in data


async def test_active_plan_tool_without_plan():
    data = await active_plan_tool(ctx=mock_ctx(MockStorage(plan=None)))
    assert data["status"] == "no_active_plan"


async def test_archived_plan_tool_lists_and_errors(storage):
    ctx = mock_ctx(storage=storage)
    assert await archived_plan_tool(ctx=ctx) == {"archived_plans": []}
    missing = await archived_plan_tool(name="nope", ctx=ctx)
    assert "error" in missing


async def test_mirror_tools_are_read_only():
    for name in ("get_coaching_context", "get_active_plan", "get_archived_plan"):
        tool = await mcp.get_tool(name)
        assert tool is not None
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


# ── Typed inputs ──────────────────────────────────────────────────────────────


async def test_structured_params_publish_their_schema():
    """A string-only schema forces the model to guess the structure."""
    for tool_name, param, model in (
        ("save_training_plan", "plan_json", "TrainingPlan"),
        ("build_and_push_workout", "workout_json", "DSLWorkout"),
        ("upload_workout", "workout_json", "DSLWorkout"),
    ):
        tool = await mcp.get_tool(tool_name)
        assert tool is not None
        schema = tool.to_mcp_tool().inputSchema
        assert model in schema.get("$defs", {}), tool_name
        assert "anyOf" in schema["properties"][param], tool_name


def test_object_or_string_input_validates():
    plan = make_plan(name="Typed")
    adapter: TypeAdapter[TrainingPlan | str] = TypeAdapter(TrainingPlan | str)
    assert isinstance(adapter.validate_python(plan.model_dump(mode="json")), TrainingPlan)
    assert isinstance(adapter.validate_python(plan.model_dump_json()), str)
    workout = {"name": "W", "steps": [{"type": "warmup", "duration": {"seconds": 600}}]}
    assert isinstance(TypeAdapter(DSLWorkout | str).validate_python(workout), DSLWorkout)


# ── next_steps / compact ──────────────────────────────────────────────────────


def test_next_steps_drive_sync_only_when_configured(monkeypatch):
    monkeypatch.delenv("OPEN_COACH_DRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("GARMIN_COACH_DRIVE_FOLDER_ID", raising=False)
    assert not any("drive_sync" in s for s in plan_update_next_steps(watch_sync=True))
    monkeypatch.setenv("OPEN_COACH_DRIVE_FOLDER_ID", "abc")
    assert any("drive_sync" in s for s in plan_update_next_steps(watch_sync=False))


def test_next_steps_watch_sync_waits_for_confirmation():
    steps = plan_update_next_steps(watch_sync=True, confirm_first=True)
    assert steps[0].startswith("Once the athlete confirms")
    assert not any("list_watch_workouts" in s for s in plan_update_next_steps(watch_sync=False))


def test_compact_payload_drops_empty_and_rounds():
    raw = {
        "a": None,
        "b": "",
        "c": [],
        "d": {"e": None},
        "f": 1.23456,
        "g": 0,
        "h": False,
        "laps": [{"x": None}, {"y": 2.0}],
    }
    assert compact_payload(raw) == {"f": 1.23, "g": 0, "h": False, "laps": [{"y": 2.0}]}
