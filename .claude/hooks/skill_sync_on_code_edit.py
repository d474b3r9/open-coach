#!/usr/bin/env python3
"""
PostToolUse hook — reminds to sync the coaching-rules skill when a coaching module changes.

Fired after Edit/Write. If the edited file is a Python module implementing coaching
logic (vdot, training_load, zones, plan_generator, race_predictor, etc.), emits a
reminder to update `.agents/skills/coaching-rules/SKILL.md` if the coaching behaviour
changes (new rule, revised calculation, adjusted pace range).

NEVER duplicate the code in the skill — the skill describes the principles, the code
implements them.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

# Force UTF-8 on stdout (the Windows cp1252 default crashes on emoji)
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8")

COACHING_MODULES = {
    "vdot.py",
    "training_load.py",
    "zones.py",
    "workout_dsl.py",
    "garmin_workout.py",
    "race_predictor.py",
    "recovery_monitor.py",
    "plan_renderer.py",
    "plan_generator.py",
}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""

    if not file_path:
        return

    fp = Path(file_path)

    if "open_coach" not in fp.parts:
        return

    # Sport plugins (sports/<key>/…) hold coaching logic too.
    if fp.name not in COACHING_MODULES and "sports" not in fp.parts:
        return

    context = (
        "⚙️ **`coaching-rules` skill reminder** — `"
        f"{fp.name}"
        "` (coaching logic) was just modified.\n\n"
        "If the **coaching behaviour changes** (new rule, revised pace, modified VDOT "
        "calculation, different default parameter), then **update "
        "`.agents/skills/coaching-rules/SKILL.md`** so the skill reflects the code.\n\n"
        "**Anti-duplication rule**: do NOT duplicate the code in the skill. The skill describes "
        'the **principles** ("rule X says Y"), the code implements them. If the code changes '
        "to fix a bug without changing the coaching behaviour, no need to touch the "
        "skill.\n\n"
        "If the change is internal (refactor, perf), no skill update is needed."
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
