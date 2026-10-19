---
name: restore-coach
description: Restores the coach state (profile, goals, constraints, plans, feedback) on a new or reinstalled machine, on any OS, from the state snapshot the Drive sync carries. Use when the athlete changes computer, reinstalls the coach, or finds an empty profile after setup while a Drive or Obsidian copy exists — "restore my coach", "new computer", "réinstaller le coach", "restaurer mon profil".
compatibility: Requires the open-coach MCP server. Drive sync (rclone) is optional but is how the snapshot reaches a new machine.
metadata:
  version: "1.0.0"
---

# Restore coach

Workflow (tools of the open-coach MCP server) to bring the coach back on another machine. The coach state lives in the coach data folder (`~/.open-coach/`), which the Drive sync does not carry; the server mirrors it into `plans/.state/` on every save (portable between Windows, Linux and macOS), and that folder travels with `plans/`.

## Steps

1. **Get the snapshot onto this machine.** If Drive sync is configured, run `bash scripts/drive_sync.sh --all` (first time on this machine: `--init-project` after a dry run, as in `docs/optional/drive-sync.md`). If you cannot run shell commands, give the athlete the command and wait. No Drive: copy the `plans/.state/` folder from the other machine into this machine's `plans/`.
2. **Preview**: `restore_coach_state()` (dry-run). Present the actions per file: `restore` (missing here), `merge` (feedback, watch uploads), `keep_local` (this machine is newer), `skip_stale` (plan already archived), `invalid`. Mention `snapshot_exported_at`.
3. **Apply** after the athlete agrees: `restore_coach_state(apply=true)`. Use `force=true` only when the athlete explicitly wants the snapshot to overwrite newer local files.
4. **Verify**: `get_coaching_context`. Summarize profile (VDOT, heart rates), goals, constraints and injuries, the active plan and its current week. Do not guess: report what the tool returns.
5. **Reconnect the watch** if no watch data comes back: the login is not in the snapshot. Follow the provider's login instructions; never retry a failed login in a loop.
6. **Reconcile the watch calendar**: `list_watch_workouts` for the coming days, compare with the restored plan, and sync only what the athlete confirms (`sync_upcoming_workouts`).

## Edge cases

- **`No state snapshot` error** → the Drive sync has not pulled `plans/.state/` yet, or the other machine never saved: on that machine call `export_coach_state`, run the Drive sync, retry.
- **Existing install, first export** → `export_coach_state` once on the machine that holds the data. It refuses to overwrite a snapshot this machine never restored (`force=true` only on purpose).
- **Nothing but markdown on Drive** (no `.state/`): rebuild with the `onboard` workflow (profile from the watch history, goals, constraints). Read `plans/athlete-profile.md` and `plans/training-journal.md` for context. A plan written by hand under `plans/archive/` is not re-importable automatically: ask the athlete, then build it with `save_training_plan` from that document.
- **Both machines changed since the last sync** → feedback and watch uploads are merged; for the profile, goals, constraints and plans the newer `updated_at` wins and the other is reported as `keep_local`. Never use `force` to settle that without asking.
- **Snapshot from a newer version** with `invalid` files → upgrade the coach on this machine, then retry.

## Output

A short report: files restored, merged, kept or skipped, the restored active plan and week, and what still needs the athlete (watch login, calendar reconciliation).
