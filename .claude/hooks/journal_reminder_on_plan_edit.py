#!/usr/bin/env python3
"""
PostToolUse hook — reminds to update the training journal after a plan/profile edit.

Fired after Edit/Write. If the edited file is a personal plan/profile located
**directly** in `<cwd>/plans/` (not in a `.templates/`, `references/`, etc.
subfolder), emits an additionalContext reminder asking to append a
"Coaching decision" entry to the journal with the **why** of the change.

No personal data is hardcoded in this file (no user-specific file names).
Extra filenames outside `plans/` to watch can be listed in
`.claude/local/hooks.config.json` → `journal_reminder.extra_watched_filenames`.

NEVER writes to the journal automatically (avoids pollution) — Claude decides
whether it is relevant when reading the reminder. Fails silently if the payload
is invalid or the config is missing.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

# Force UTF-8 on stdout (the Windows cp1252 default crashes on emoji)
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8")


# Subfolders of `plans/` that are NOT personal plans (versioned templates,
# external reference corpus, private files excluded from the nudge).
EXCLUDED_PLANS_SUBDIRS = {".templates", "references", "archive"}

# Files in plans/ that are NOT coaching plans and must not trigger the journal
# reminder (the journal itself, private technical files).
EXCLUDED_FILENAMES = {
    "training-journal.md",
    "journal-coureur.md",  # legacy name
    "learnings.private.md",
}


def _load_local_config(cwd: Path) -> dict:
    """Read .claude/local/hooks.config.json if present. Return {} otherwise."""
    cfg_path = cwd / ".claude" / "local" / "hooks.config.json"
    try:
        with cfg_path.open(encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _is_personal_plan_file(file_path: Path, cwd: Path) -> bool:
    """True if the file is a *.md located *directly* in <cwd>/plans/.

    Explicitly excludes:
    - the .templates/, references/, archive/ subfolders (not active plans)
    - files outside the repo (e.g. C:/Users/.../.claude/plans/, which is Claude
      Code's internal implementation-plans folder, not the coaching repo's
      plans folder)
    - the journal itself (to avoid a loop)
    """
    name = file_path.name.lower()
    if name in EXCLUDED_FILENAMES:
        return False
    if not name.endswith(".md"):
        return False

    # The file must be directly in <cwd>/plans/ (parent.name == "plans"
    # AND parent.parent == cwd). Not a subfolder; not another "plans" folder
    # elsewhere on disk.
    try:
        parent = file_path.parent.resolve()
        cwd_resolved = cwd.resolve()
    except OSError:
        return False

    if parent.name != "plans":
        return False
    if parent.parent != cwd_resolved:
        return False
    # Extra safeguard: no excluded subfolder
    return file_path.parent.name not in EXCLUDED_PLANS_SUBDIRS


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_input = payload.get("tool_input") or {}
    file_path_raw = tool_input.get("file_path") or ""
    cwd_raw = payload.get("cwd") or "."

    if not file_path_raw:
        return

    fp = Path(file_path_raw)
    cwd = Path(cwd_raw)

    config = _load_local_config(cwd)
    extra = (config.get("journal_reminder") or {}).get("extra_watched_filenames") or []
    extra_set = {n.lower() for n in extra if isinstance(n, str)}

    is_watched = _is_personal_plan_file(fp, cwd) or fp.name.lower() in extra_set
    if not is_watched:
        return

    context = (
        "**Journal reminder** — `"
        f"{fp.name}"
        "` was just modified.\n\n"
        "If the change is a **plan decision**, a **VDOT/pace recalibration**, "
        "a **structural change** (phase, volume, test), or an **adaptation following an "
        "athlete event**, then **append an entry to the training journal** "
        "(`plans/training-journal.md`) in the relevant section "
        "(Coaching decisions / Athlete insights / Metric changes) with:\n"
        "- ISO date + visual tag\n"
        "- 1-3 lines summarising the change\n"
        "- **the why** (the reason matters more than the what in the long run)\n\n"
        "If the change is cosmetic (typo, rewording), no journal entry is needed."
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
