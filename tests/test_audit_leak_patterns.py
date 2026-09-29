"""Unit tests for the structural leak patterns in `scripts/audit_docs.py`.

The default pattern list must (a) fire on shapes that are personal by nature
and (b) stay silent on the placeholders used throughout the docs, including
the audit script itself.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_audit_module() -> ModuleType:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("audit_docs", SCRIPTS_DIR / "audit_docs.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit_docs = _load_audit_module()
LEAK_RE = audit_docs._LEAK_RE


@pytest.mark.parametrize(
    "line",
    [
        "REPO_DIR=/home/alice/projects/coach/plans/",
        "vault: /Users/bob/Documents/vault/",
        r"set OPEN_COACH_OBSIDIAN_PLANS_DIR=C:\Users\carol\Obsidian\plans\ ",
        "contact: alice.runner@gmail.com",
        "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        'export OPEN_COACH_DRIVE_FOLDER_ID="1AbCdEfGhIjKlMnOpQrStUvWxYz012345"',
        'GARMIN_PASSWORD="hunter2secret"',
        '"oauth_token": "abcdefghijklmnopqrstuvwxyz0123456789"',
    ],
)
def test_default_patterns_fire_on_personal_shapes(line: str) -> None:
    assert LEAK_RE.search(line), line


@pytest.mark.parametrize(
    "line",
    [
        "export OPEN_COACH_REPO_PLANS_DIR=/home/you/open-coach/plans",
        r'"C:\Users\you\path\to\plans"',
        "/c/Users/you/path/to/plans",
        "cd /home/<user>/repo/",
        'export GARMIN_EMAIL="you@example.com"',
        "runner@example.com",
        "Jane Doe <12345678+janedoe@users.noreply.github.com>",
        '"GARMIN_PASSWORD": "${GARMIN_PASSWORD}"',
        "GARMIN_PASSWORD=<your-password>",
        "export OPEN_COACH_DRIVE_FOLDER_ID=<folder-id>",
        "~/.open-coach/strava_tokens.json",
        "Coaching data lives in ~/.open-coach/ (outside the project)",
    ],
)
def test_default_patterns_ignore_placeholders(line: str) -> None:
    assert not LEAK_RE.search(line), line


def test_default_patterns_are_structural() -> None:
    """Structural only: a plain word (a name, a city, a race) is not a default pattern."""
    for pattern in audit_docs._DEFAULT_LEAK_PATTERNS:
        assert re.search(r"[\\\[\](?]", pattern), f"plain-word pattern: {pattern}"


# ── Check 7: French guard ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "Lire la fiche avant chaque séance.",
        "10 km dont 15 min @ M pour la semaine",
        'msg = "footing tranquille"',
    ],
)
def test_french_guard_flags_french(line: str) -> None:
    assert audit_docs.find_french_lines("docs/example.md", line) != []


@pytest.mark.parametrize(
    ("rel_path", "text"),
    [
        ("docs/example.md", "Plain English about pace and a long run."),
        ("skills/x/SKILL.md", 'description: Trigger on "règle", "méthodo".'),
        ("CLAUDE.md", "Skip `strength` (legacy name `kiné-renfo`)."),
        ("README.md", "Prompts work in French (*Analyse mes séances*)."),
        ("x.py", 'TABLE = "éèê"  # fr-ok'),
        ("docs/g.md", "## French / English equivalents\n| footing | easy run |\n"),
        ("src/open_coach/i18n.py", '"fr": "Sortie longue"'),
        ("tests/test_x.py", '"Footing tranquille"'),
        ("plans/.templates/athlete-profile.fr.template.md", "## Contraintes physiques"),
    ],
)
def test_french_guard_allows_intentional_french(rel_path: str, text: str) -> None:
    assert audit_docs.find_french_lines(rel_path, text) == []


def test_french_guard_section_ends_at_next_heading() -> None:
    text = "## French glossary\n| footing | easy |\n## Rules\nUne séance.\n"
    assert audit_docs.find_french_lines("docs/g.md", text) == [(4, "Une séance.")]
