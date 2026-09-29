"""Live smoke-test for every MCP tool/resource.

Introspects the FastMCP registry (no hardcoded tool list) and, through the
real lifespan:
1. Calls every tool annotated readOnlyHint=True with sample arguments.
2. Verifies every other (mutating) tool is registered with a valid schema.
3. Reads every registered resource function directly.

Mutating tools are NEVER invoked. Run from the project root with:

    uv run python scripts/smoke_mcp.py

Requires a valid Garmin token cache (~/.garth/) — this hits the real API.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastmcp.resources.function_resource import FunctionResource
from fastmcp.tools.function_tool import FunctionTool

from open_coach import server as s

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import ensure_utf8_stdout

# Sample arguments per read-only tool (only non-default args need an entry).
SAMPLE_ARGS: dict[str, dict[str, Any]] = {
    "get_recent_runs": {"days": 14, "limit": 10},
    "get_training_load": {"days": 60},
    "get_training_zones": {"vdot": 50.0},
    "calculate_vdot_from_race": {"distance_meters": 10000, "time_seconds": 2400},
    "get_strava_activities": {"months": 1, "activity_type": "Run"},
    # get_activity_details needs a real id — resolved at runtime from get_recent_runs.
}


def _mk_ctx(lifespan_ctx: dict) -> SimpleNamespace:
    # Matches the FastMCP Context contract for both access forms
    # (ctx.lifespan_context and ctx.request_context.lifespan_context).
    return SimpleNamespace(
        lifespan_context=lifespan_ctx,
        request_context=SimpleNamespace(lifespan_context=lifespan_ctx),
    )


def _summarize(result: Any) -> str:
    if isinstance(result, dict):
        keys = list(result.keys())[:4]
        return f"dict({len(result)} keys) e.g. {keys}"
    if isinstance(result, list):
        return f"list({len(result)} items)"
    return type(result).__name__


async def main() -> int:
    failed: list[tuple[str, str]] = []
    ok_count = 0

    tools = [t for t in await s.mcp.list_tools() if isinstance(t, FunctionTool)]
    resources = [r for r in await s.mcp.list_resources() if isinstance(r, FunctionResource)]
    templates = await s.mcp.list_resource_templates()

    read_only = [t for t in tools if t.annotations and t.annotations.readOnlyHint]
    mutating = [t for t in tools if t not in read_only]

    async with s.coach_lifespan(s.mcp) as lifespan_ctx:
        ctx = _mk_ctx(lifespan_ctx)

        # Resolve a sample activity id for get_activity_details
        runs_tool = next((t for t in read_only if t.name == "get_recent_runs"), None)
        if runs_tool is not None:
            runs = await runs_tool.fn(days=14, limit=5, ctx=ctx)
            activities = runs.get("activities", []) if isinstance(runs, dict) else []
            sample_aid = next((r.get("activity_id") for r in activities), None)
            if sample_aid:
                SAMPLE_ARGS["get_activity_details"] = {"activity_id": sample_aid}

        print(f"=== read-only tools ({len(read_only)}) ===")
        for tool in read_only:
            fn = tool.fn
            kwargs = dict(SAMPLE_ARGS.get(tool.name, {}))
            if tool.name == "get_activity_details" and "activity_id" not in kwargs:
                print(f"[SKIP] {tool.name} — no sample activity_id")
                continue
            if "ctx" in inspect.signature(fn).parameters:
                kwargs["ctx"] = ctx
            try:
                result = await fn(**kwargs)
                if result is None:
                    failed.append((tool.name, "returned None"))
                    print(f"[FAIL] {tool.name:<32} -> returned None")
                else:
                    ok_count += 1
                    print(f"[ OK ] {tool.name:<32} -> {_summarize(result)}")
            except Exception as exc:
                failed.append((tool.name, f"{type(exc).__name__}: {exc}"))
                print(f"[FAIL] {tool.name:<32} -> {type(exc).__name__}: {exc}")

        print(f"\n=== mutating tools ({len(mutating)}) — schema check only ===")
        for tool in mutating:
            schema = tool.parameters
            if isinstance(schema, dict) and schema.get("type") == "object":
                ok_count += 1
                n_params = len(schema.get("properties", {}))
                print(f"[ OK ] {tool.name:<32} -> registered, {n_params} params")
            else:
                failed.append((tool.name, "invalid or missing input schema"))
                print(f"[FAIL] {tool.name:<32} -> invalid schema")

        print(f"\n=== resources ({len(resources)} + {len(templates)} templates) ===")
        for res in resources:
            try:
                out = res.fn(ctx=ctx)
                if not isinstance(out, str) or not out:
                    failed.append((str(res.uri), "non-string or empty"))
                    print(f"[FAIL] {res.uri}")
                else:
                    ok_count += 1
                    print(f"[ OK ] {res.uri!s:<32} -> {len(out)} bytes")
            except Exception as exc:
                failed.append((str(res.uri), f"{type(exc).__name__}: {exc}"))
                print(f"[FAIL] {res.uri!s:<32} -> {type(exc).__name__}: {exc}")
        for tpl in templates:
            # Templates need a parameter — verify registration only.
            ok_count += 1
            print(f"[ OK ] {tpl.uri_template!s:<32} -> registered (template)")

    print(f"\n=== summary: {ok_count} ok / {len(failed)} fail ===")
    for n, why in failed:
        print(f"  {n}: {why}")
    return 0 if not failed else 1


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(asyncio.run(main()))
