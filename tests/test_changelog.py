"""CHANGELOG.md: one section per pull request (or release), newest first."""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

# `## #26 — feat(state): … (2026-10-19)` or `## 0.2.0 — Initial public release (2026-09-29)`
_HEADING = re.compile(
    r"^## (?P<id>#\d+|\d+\.\d+\.\d+) — (?P<title>.+) \((?P<date>\d{4}-\d{2}-\d{2})\)$"
)
_GROUPS = {"Added", "Changed", "Fixed", "Removed", "Notes"}


def _sections() -> list[tuple[str, str, date, str]]:
    """(id, title, date, body) for every `## ` section, in file order."""
    out = []
    parts = re.split(r"(?m)^(?=## )", TEXT)
    for part in parts[1:]:
        first, _, body = part.partition("\n")
        match = _HEADING.match(first)
        assert match, f"malformed heading: {first!r} (expected '## #<PR> — <title> (<YYYY-MM-DD>)')"
        out.append((match["id"], match["title"], date.fromisoformat(match["date"]), body))
    return out


def test_title_and_sections_exist() -> None:
    assert TEXT.startswith("# Changelog\n")
    assert len(_sections()) >= 2


def test_every_heading_is_well_formed_and_unique() -> None:
    ids = [s[0] for s in _sections()]
    assert len(ids) == len(set(ids)), "duplicate section"


def test_sections_are_newest_first() -> None:
    dates = [s[2] for s in _sections()]
    assert dates == sorted(dates, reverse=True), "sections must be ordered newest first"


def test_no_unreleased_section() -> None:
    assert "Unreleased" not in TEXT


def test_every_section_has_content_and_known_groups() -> None:
    for ident, _, _, body in _sections():
        assert re.search(r"(?m)^- ", body), f"{ident}: no bullet"
        for group in re.findall(r"(?m)^### (.+)$", body):
            assert group in _GROUPS, f"{ident}: unknown group {group!r}"


def test_latest_release_matches_pyproject() -> None:
    versions = [s[0] for s in _sections() if not s[0].startswith("#")]
    assert versions, "no release section"
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert versions[0] == declared
