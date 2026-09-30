"""Smoke test for `scripts/audit_docs.py` (all 6 audit checks).

Runs the versioned audit script as a subprocess and asserts a clean exit.
The script performs seven structural checks (personal-data leak in versioned
files, doc consistency, no French in versioned text, ...) — a non-zero exit turns the
test suite red long before an offending commit can reach a public push.

The audit script is the single source of truth for what is checked; updating
it (e.g. adding a new pattern to the blocklist) automatically propagates here.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "audit_docs.py"


def test_audit_docs_passes() -> None:
    """`scripts/audit_docs.py` must exit 0 — non-zero exit = audit failure."""
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if result.returncode != 0:
        # Surface the audit output so the developer sees the exact failing check
        pytest.fail(
            f"scripts/audit_docs.py failed (exit {result.returncode}).\n"
            "If it flags personal data, move the offending content into a gitignored "
            "path (plans/, ~/.open-coach/, .claude/local/) and rerun.\n\n"
            f"--- audit_docs.py stdout ---\n{result.stdout}\n"
            f"--- audit_docs.py stderr ---\n{result.stderr}"
        )
