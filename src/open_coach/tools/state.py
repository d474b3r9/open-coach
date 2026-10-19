"""MCP tools to move the coach state between machines (Windows, Linux, macOS).

The state (profile, goals, constraints, plans, feedback) is mirrored into
``plans/.state/`` on every save; the optional Drive sync carries that folder.
``restore_coach_state`` imports it on the other machine, ``export_coach_state``
writes it on demand (first export of an existing install).
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from open_coach.paths import env
from open_coach.server import mcp
from open_coach.state_snapshot import default_snapshot_dir, export_state, restore_state


def _drive_step() -> list[str]:
    if not env("DRIVE_FOLDER_ID"):
        return []
    return [
        "If you can run shell commands: run `bash scripts/drive_sync.sh --all` to push the "
        "snapshot to Drive, and report the rclone outcome in one line."
    ]


@mcp.tool(annotations={"idempotentHint": True})
async def export_coach_state(force: bool = False, ctx: Context | None = None) -> dict[str, Any]:
    """Write the coach state (profile, goals, constraints, plans, feedback) to plans/.state/.

    The snapshot is also refreshed automatically after every save; call this once
    on an existing install so a second machine can restore it, or to refresh it
    on demand. Refuses to overwrite a snapshot this machine never restored
    (restore_coach_state first) unless force=true.

    Args:
        force: Overwrite an existing snapshot this machine never restored.

    Returns:
        {"snapshot_dir", "files", "updated", "unchanged", "next_steps"} or {"error": str}.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    snap = storage.snapshot_dir or default_snapshot_dir()
    result = export_state(storage.base_dir, snap, force=force)
    if "error" not in result:
        result["next_steps"] = _drive_step()
    return result


@mcp.tool(annotations={"destructiveHint": True})
async def restore_coach_state(
    apply: bool = False, force: bool = False, ctx: Context | None = None
) -> dict[str, Any]:
    """Import the coach state snapshot (plans/.state/) into this machine's coach data.

    Use on a new or reinstalled machine after the Drive sync has pulled `plans/`
    (any OS: the snapshot is portable). Dry-run by default: it lists, per file,
    whether it would be restored, merged (feedback, watch uploads), kept (local
    is newer), skipped (stale active plan) or is invalid. Review it with the
    athlete, then call again with apply=true. force=true overwrites newer local
    files: only after the athlete agrees.

    Args:
        apply: Write the changes (default: preview only).
        force: Let the snapshot overwrite local files that are newer.

    Returns:
        {"dry_run", "snapshot_dir", "snapshot_exported_at", "actions", "summary",
        "next_steps"} or {"error": str}.
    """
    assert ctx is not None
    storage = ctx.lifespan_context["storage"]
    snap = storage.snapshot_dir or default_snapshot_dir()
    result = restore_state(storage.base_dir, snap, apply=apply, force=force)
    if "error" in result:
        return result
    if apply:
        result["next_steps"] = [
            "Call get_coaching_context and show the athlete what was restored (profile, goals, "
            "constraints, active plan).",
            "The watch login is not part of the snapshot: if no watch is connected, follow the "
            "provider's login instructions (never retry a failed login in a loop).",
            "Do not push anything to the watch automatically: list_watch_workouts first, then "
            "sync only what the athlete confirms.",
        ]
    else:
        result["next_steps"] = [
            "Show the athlete this preview. If it looks right, call "
            "restore_coach_state(apply=true); use force=true only if they accept that the "
            "snapshot overwrites newer local files."
        ]
    return result
