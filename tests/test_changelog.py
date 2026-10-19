"""scripts/changelog.py: the changelog is fed from the pull request, and checked."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))  # the script imports its sibling `_console`
_spec = importlib.util.spec_from_file_location("changelog_script", SCRIPTS / "changelog.py")
assert _spec is not None
assert _spec.loader is not None
cs: Any = importlib.util.module_from_spec(_spec)
sys.modules["changelog_script"] = cs
_spec.loader.exec_module(cs)

PREAMBLE = "# Changelog\n\nIntro.\n\n"
OLD = (
    "## #5 — fix(core): old (2026-10-01)\n\n- Old thing.\n\n"
    "## 0.2.0 — Initial public release (2026-09-29)\n\n### Added\n\n- Everything.\n"
)
BASE = PREAMBLE + OLD


def _body(*bullets: str) -> str:
    items = "\n".join(f"- {b}" for b in bullets)
    return f"## What and why\n\nx\n\n## Changelog\n\n{items}\n\n## Checklist\n"


def _sync(tmp_path: Path, *argv: str) -> tuple[int, str]:
    """Run `sync` (or `lint`) on a temporary copy of BASE; return (exit code, file text)."""
    path = tmp_path / "CHANGELOG.md"
    if not path.exists():
        path.write_text(BASE, encoding="utf-8")
    code = cs.main([*argv, "--changelog", str(path)])
    return code, path.read_text(encoding="utf-8")


def _offline(tmp_path: Path, body: str, title: str = "feat: new") -> list[str]:
    path = tmp_path / "body.md"
    path.write_text(body, encoding="utf-8")
    return ["sync", "--number", "7", "--title", title, "--body-file", str(path)]


# ── the real changelog ──


def test_the_real_changelog_is_valid() -> None:
    assert cs.main(["lint"]) == 0


# ── the PR description block ──


def test_block_bullets_and_continuation_lines() -> None:
    body = "## Changelog\n\n- First\n  continues here\n- Second\n\n## Other\n- not this\n"
    block = cs.extract_block(body)
    assert block.present
    assert block.bullets == ("First\n  continues here", "Second")


def test_block_comments_are_stripped_and_crlf_is_read() -> None:
    body = "## Changelog\r\n<!-- explain -->\r\n- One\r\n"
    assert cs.extract_block(body).bullets == ("One",)


@pytest.mark.parametrize("text", ["None", "none.", "NONE\n"])
def test_block_none(text: str) -> None:
    block = cs.extract_block(f"## Changelog\n\n{text}\n")
    assert block.present
    assert block.none


def test_block_absent_or_left_empty() -> None:
    assert not cs.extract_block("## What and why\n").present
    left_empty = cs.extract_block("## Changelog\n\n<!-- fill me -->\n- \n")
    assert left_empty.present
    assert not left_empty.none
    assert left_empty.bullets == ()


# ── the section ──


def test_insert_goes_first_and_is_idempotent() -> None:
    text, status = cs.upsert(BASE, 7, "feat: new", ("Did it.",), "2026-10-19")
    assert status == "inserted"
    assert text.index("## #7") < text.index("## #5")
    assert text.startswith(PREAMBLE)
    again, status = cs.upsert(text, 7, "feat: new", ("Did it.",), None)
    assert status == "unchanged"
    assert again == text


def test_update_keeps_the_date_unless_given() -> None:
    text, _ = cs.upsert(BASE, 7, "feat: new", ("Did it.",), "2026-10-19")
    kept, status = cs.upsert(text, 7, "feat: renamed", ("Did more.",), None)
    assert status == "updated"
    assert "## #7 — feat: renamed (2026-10-19)" in kept
    moved, _ = cs.upsert(kept, 7, "feat: renamed", ("Did more.",), "2026-10-20")
    assert "(2026-10-20)" in moved


def test_other_sections_are_untouched_and_file_ends_with_one_newline() -> None:
    text, _ = cs.upsert(BASE, 7, "feat: new", ("A", "B"), "2026-10-19")
    assert OLD in text
    assert text.endswith("- Everything.\n")
    assert not text.endswith("\n\n")


def test_check_section_problems() -> None:
    text, _ = cs.upsert(BASE, 7, "feat: new", ("Did it.",), "2026-10-19")
    assert cs.check_section(text, 7, "feat: new", ("Did  it.",)) == []  # whitespace only
    assert cs.check_section(text, 8, "feat: new", ("Did it.",))[0].startswith("CHANGELOG.md has no")
    assert "title" in cs.check_section(text, 7, "feat: other", ("Did it.",))[0]
    assert "bullets" in cs.check_section(text, 7, "feat: new", ("Else.",))[0]


def test_check_ignores_the_date() -> None:
    text, _ = cs.upsert(BASE, 7, "feat: new", ("Did it.",), "2026-01-01")
    assert cs.check_section(text, 7, "feat: new", ("Did it.",)) == []


# ── the PR title ──


@pytest.mark.parametrize(
    "title",
    [
        "feat: make it work",
        "fix(scripts): await coach:// resources in smoke_mcp",
        "docs(drive-sync): move the guide, add notes",
        "refactor(sports)!: drop the old protocol",
        'Revert "feat: x"',
        "Merge branch 'main' into x",
        "fixup! feat: x",
    ],
)
def test_valid_titles(title: str) -> None:
    assert cs.check_title(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "",
        "update stuff",
        "Feat: x",
        "feat:x",
        "feat: ",
        "wip: x",
        "feat(): x",
        "feat: " + "x" * 130,
    ],
)
def test_invalid_titles(title: str) -> None:
    assert cs.check_title(title) is not None


# ── lint ──


def test_lint_accepts_a_valid_changelog() -> None:
    assert cs.lint_text(BASE, "0.2.0") == []


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda t: t.replace("(2026-10-01)", "(2026-01-01)"), "newest first"),
        (lambda t: t.replace("## #5", "## [Unreleased]\n\n- x\n\n## #5"), "malformed heading"),
        (lambda t: t + "\n## #5 — fix: dup (2026-09-01)\n\n- x\n", "duplicate"),
        (lambda t: t.replace("- Old thing.", "No bullet here."), "no bullet"),
        (lambda t: t.replace("### Added", "### Invented"), "unknown group"),
        (lambda t: t.replace("## 0.2.0", "## 9.9.9"), "pyproject version"),
        (lambda t: t.replace("(2026-10-01)", "(2026-13-45)"), "invalid date"),
        (lambda t: t.replace("# Changelog", "# Log", 1), "must start with"),
    ],
)
def test_lint_rejects(mutate: Any, needle: str) -> None:
    errors = cs.lint_text(mutate(BASE), "0.2.0")
    assert any(needle in e for e in errors), errors


# ── pull request sources ──


def _event(tmp_path: Path, **pr: Any) -> str:
    fields = {
        "number": 9,
        "title": "feat: x",
        "body": _body("Bullet."),
        "user": {"login": "alice"},
        "labels": [],
        **pr,
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"pull_request": fields}), encoding="utf-8")
    return str(path)


def test_event_is_parsed(tmp_path: Path) -> None:
    pr = cs.load_event(_event(tmp_path))
    assert (pr.number, pr.title, pr.author) == (9, "feat: x", "alice")
    assert not pr.exempt


def test_bots_and_the_skip_label_are_exempt(tmp_path: Path) -> None:
    assert cs.load_event(_event(tmp_path, user={"login": "dependabot[bot]"})).exempt
    assert cs.load_event(_event(tmp_path, labels=[{"name": "skip-changelog"}])).exempt


def test_a_non_pull_request_event_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "e.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="pull_request"):
        cs.load_event(str(path))


# ── commands ──


def test_sync_then_check_offline(tmp_path: Path) -> None:
    argv = _offline(tmp_path, _body("Did it.", "Did more."))
    code, text = _sync(tmp_path, *argv, "--date", "2026-10-19")
    assert code == 0
    assert "## #7 — feat: new (2026-10-19)" in text
    assert _sync(tmp_path, *argv, "--check")[0] == 0
    other = _offline(tmp_path, _body("Did it.", "Did more."), title="feat: other")
    assert _sync(tmp_path, *other, "--check")[0] == 1


def test_check_does_not_write(tmp_path: Path) -> None:
    code, text = _sync(tmp_path, *_offline(tmp_path, _body("Did it.")), "--check")
    assert code == 1
    assert text == BASE


def test_missing_block_fails_with_the_fix_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, text = _sync(tmp_path, *_offline(tmp_path, "## What and why\n\nx\n"))
    assert code == 1
    assert text == BASE
    assert "scripts/changelog.py sync --pr 7" in capsys.readouterr().out


def test_none_block_writes_nothing(tmp_path: Path) -> None:
    code, text = _sync(tmp_path, *_offline(tmp_path, "## Changelog\n\nNone\n", "chore: x"))
    assert code == 0
    assert text == BASE


def test_exempt_event_passes_without_a_block(tmp_path: Path) -> None:
    event = _event(tmp_path, body="", user={"login": "dependabot[bot]"})
    assert _sync(tmp_path, "sync", "--event", event, "--check")[0] == 0
    assert cs.main(["title", "--event", event]) == 0


def test_title_command_reads_the_event_and_the_commit_message(tmp_path: Path) -> None:
    assert cs.main(["title", "--event", _event(tmp_path)]) == 0
    assert cs.main(["title", "--event", _event(tmp_path, title="bad title")]) == 1
    message = tmp_path / "msg"
    message.write_text("# git comment\nfeat(x): ok\n\nbody\n", encoding="utf-8")
    assert cs.main(["title", "--commit-msg-file", str(message)]) == 0
    message.write_text("nope\n", encoding="utf-8")
    assert cs.main(["title", "--commit-msg-file", str(message)]) == 1


def test_untrusted_text_never_starts_a_workflow_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cs.main(["title", "::error::boom\n::set-output name=x::y"]) == 1
    for line in capsys.readouterr().out.splitlines():
        assert not line.startswith("::")


def test_gh_missing_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    assert cs.main(["sync"]) == 2
    assert "--body-file" in capsys.readouterr().out


def test_gh_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 1, "", "no pull request found"),
    )
    assert cs.main(["sync", "--pr", "1"]) == 2
    assert "no pull request found" in capsys.readouterr().out
