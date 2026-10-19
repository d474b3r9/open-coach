#!/usr/bin/env python3
"""Feed CHANGELOG.md from the pull request: one section per PR.

The pull request is the single source: its number, its title (the squash
subject) and a ``## Changelog`` block in its description (bullets, or ``None``).
The same code writes the section locally and checks it in CI.

Usage (stdlib only; ``gh`` is only needed to read a PR from GitHub):

    uv run python scripts/changelog.py sync                 # PR of the current branch
    uv run python scripts/changelog.py sync --pr 27
    uv run python scripts/changelog.py sync --number 27 --title "feat: x" --body-file body.md
    uv run python scripts/changelog.py sync --event "$GITHUB_EVENT_PATH" --check   # CI
    uv run python scripts/changelog.py title "feat(scope): summary"
    uv run python scripts/changelog.py title --commit-msg-file .git/COMMIT_EDITMSG
    uv run python scripts/changelog.py lint

Security (public repository): a PR title and body are untrusted. They are read
from the event file or from ``gh``, never through a shell, never interpolated
in a workflow. Untrusted text is printed indented so it can never start a line
with ``::`` (a GitHub Actions workflow command).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from _console import ensure_utf8_stdout, utf8_print

REPO = Path(__file__).resolve().parent.parent
CHANGELOG = REPO / "CHANGELOG.md"
PYPROJECT = REPO / "pyproject.toml"

TYPES = (
    "feat",
    "fix",
    "docs",
    "chore",
    "refactor",
    "test",
    "ci",
    "build",
    "perf",
    "style",
    "revert",
)
GROUPS = {"Added", "Changed", "Fixed", "Removed", "Notes"}
SKIP_LABEL = "skip-changelog"

_TITLE = re.compile(rf"^(?:{'|'.join(TYPES)})(?:\([a-z0-9][a-z0-9/_.-]*\))?!?: \S.{{0,118}}$")
# `## #26 — feat(state): … (2026-10-19)` or `## 0.2.0 — Initial public release (2026-09-29)`
_HEADING = re.compile(
    r"^## (?P<id>#\d+|\d+\.\d+\.\d+) — (?P<title>.+) \((?P<date>\d{4}-\d{2}-\d{2})\)$"
)
# Subjects git or the merge tooling write on their own: never reject them.
_AUTO_SUBJECTS = ("Merge ", 'Revert "', "fixup! ", "squash! ", "amend! ")


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    author: str
    labels: tuple[str, ...]

    @property
    def exempt(self) -> bool:
        """Bots and PRs labelled ``skip-changelog`` have no changelog entry to check."""
        return self.author.endswith("[bot]") or SKIP_LABEL in self.labels


@dataclass(frozen=True)
class Block:
    """The ``## Changelog`` block of a PR description."""

    present: bool
    none: bool = False
    bullets: tuple[str, ...] = ()


# ── output ──


def say(message: str) -> None:
    utf8_print(message)


def quote(text: str) -> str:
    """Untrusted text, indented so no line can start with ``::``."""
    return "\n".join("    " + line for line in text.splitlines()) or "    (empty)"


# ── PR description → bullets ──


def extract_block(body: str) -> Block:
    """Read the ``## Changelog`` block: bullets, ``None``, or absent."""
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    start = re.search(r"(?mi)^##[ \t]+changelog[ \t]*$", text)
    if start is None:
        return Block(present=False)
    rest = text[start.end() :]
    end = re.search(r"(?m)^## ", rest)
    block = rest[: end.start()] if end else rest
    if re.fullmatch(r"(?i)none\.?", block.strip()):
        return Block(present=True, none=True)
    bullets: list[str] = []
    current: str | None = None
    for line in block.split("\n"):
        if line.startswith("- "):
            if current is not None:
                bullets.append(current)
            current = line[2:].rstrip()
        elif not line.strip():
            continue
        elif current is not None and line[:1] in " \t":
            current += "\n  " + line.strip()
        else:
            if current is not None:
                bullets.append(current)
            current = None
    if current is not None:
        bullets.append(current)
    return Block(present=True, bullets=tuple(b for b in bullets if b.strip()))


# ── CHANGELOG.md ──


def split_sections(text: str) -> tuple[str, list[str]]:
    """(text before the first ``## ``, one string per ``## `` section)."""
    parts = re.split(r"(?m)^(?=## )", text)
    return parts[0], parts[1:]


def render_section(number: int, title: str, bullets: tuple[str, ...], day: str) -> str:
    heading = f"## #{number} — {' '.join(title.split())} ({day})"
    return "\n".join([heading, "", *(f"- {b}" for b in bullets)]) + "\n\n"


def _normalise(bullet: str) -> str:
    return " ".join(bullet.split())


def _section_bullets(part: str) -> list[str]:
    bullets: list[str] = []
    for line in part.split("\n")[1:]:
        if line.startswith("- "):
            bullets.append(line[2:])
        elif bullets and line[:1] in " \t" and line.strip():
            bullets[-1] += "\n" + line
    return bullets


def _find(parts: list[str], number: int) -> int | None:
    for i, part in enumerate(parts):
        match = _HEADING.match(part.split("\n", 1)[0])
        if match and match["id"] == f"#{number}":
            return i
    return None


def upsert(
    text: str, number: int, title: str, bullets: tuple[str, ...], day: str | None
) -> tuple[str, str]:
    """Insert or update the section of PR *number*. Returns (new text, status).

    Status is ``inserted``, ``updated`` or ``unchanged``. An existing section
    keeps its date unless *day* is given; a new one defaults to today.
    """
    preamble, parts = split_sections(text)
    index = _find(parts, number)
    if index is None:
        parts.insert(0, render_section(number, title, bullets, day or date.today().isoformat()))
        status = "inserted"
    else:
        kept = _HEADING.match(parts[index].split("\n", 1)[0])
        assert kept is not None
        new = render_section(number, title, bullets, day or kept["date"])
        status = "unchanged" if new.rstrip("\n") == parts[index].rstrip("\n") else "updated"
        parts[index] = new
    return (preamble + "".join(parts)).rstrip("\n") + "\n", status


def check_section(text: str, number: int, title: str, bullets: tuple[str, ...]) -> list[str]:
    """Problems between the PR and its section (the date is the merge day: ignored)."""
    _, parts = split_sections(text)
    index = _find(parts, number)
    if index is None:
        return [f"CHANGELOG.md has no section for #{number}"]
    problems: list[str] = []
    match = _HEADING.match(parts[index].split("\n", 1)[0])
    assert match is not None
    if match["title"] != " ".join(title.split()):
        problems.append(f"the heading of #{number} does not match the PR title")
    have = [_normalise(b) for b in _section_bullets(parts[index])]
    if have != [_normalise(b) for b in bullets]:
        problems.append(f"the bullets of #{number} do not match the PR `## Changelog` block")
    return problems


def lint_text(text: str, version: str | None) -> list[str]:
    """Structural problems of a changelog (empty list = valid)."""
    errors: list[str] = []
    if not text.startswith("# Changelog\n"):
        errors.append("must start with '# Changelog'")
    _, parts = split_sections(text)
    if not parts:
        errors.append("no section")
    seen: set[str] = set()
    days: list[str] = []
    releases: list[str] = []
    for part in parts:
        first, _, body = part.partition("\n")
        match = _HEADING.match(first)
        if match is None:
            errors.append(f"malformed heading: {first!r} (expected '## #<PR> — <title> (<date>)')")
            continue
        ident = match["id"]
        if ident in seen:
            errors.append(f"{ident}: duplicate section")
        seen.add(ident)
        try:
            date.fromisoformat(match["date"])
        except ValueError:
            errors.append(f"{ident}: invalid date {match['date']!r}")
        days.append(match["date"])
        if not re.search(r"(?m)^- ", body):
            errors.append(f"{ident}: no bullet")
        errors += [
            f"{ident}: unknown group {g!r}"
            for g in re.findall(r"(?m)^### (.+)$", body)
            if g not in GROUPS
        ]
        if not ident.startswith("#"):
            releases.append(ident)
    if days != sorted(days, reverse=True):
        errors.append("sections must be ordered newest first")
    if not releases:
        errors.append("no release section")
    elif version is not None and releases[0] != version:
        errors.append(f"latest release {releases[0]} is not the pyproject version {version}")
    return errors


# ── pull request sources ──


def load_event(path: str) -> PullRequest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pr = data.get("pull_request")
    if not isinstance(pr, dict):
        raise ValueError("the event file is not a pull_request event")
    return PullRequest(
        number=int(pr.get("number") or data.get("number")),
        title=str(pr.get("title") or ""),
        body=str(pr.get("body") or ""),
        author=str((pr.get("user") or {}).get("login") or ""),
        labels=tuple(str(label.get("name")) for label in pr.get("labels") or []),
    )


def gh_pull_request(number: int | None) -> PullRequest:
    argv = ["gh", "pr", "view", *([str(number)] if number else [])]
    argv += ["--json", "number,title,body,author,labels"]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gh is not installed: pass --number, --title and --body-file instead"
        ) from exc
    if done.returncode != 0:
        raise RuntimeError(f"gh could not read the pull request: {done.stderr.strip()}")
    data = json.loads(done.stdout)
    return PullRequest(
        number=int(data["number"]),
        title=str(data["title"]),
        body=str(data.get("body") or ""),
        author=str((data.get("author") or {}).get("login") or ""),
        labels=tuple(str(label["name"]) for label in data.get("labels") or []),
    )


def _pull_request(args: argparse.Namespace) -> PullRequest:
    if args.event:
        return load_event(args.event)
    if args.number is not None:
        if not args.title:
            raise RuntimeError("--number needs --title")
        body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
        return PullRequest(args.number, args.title, body, "", ())
    return gh_pull_request(args.pr)


# ── commands ──


def check_title(title: str) -> str | None:
    """None when the title follows ``type(scope)!: summary``, else the reason."""
    if title.startswith(_AUTO_SUBJECTS):
        return None
    if _TITLE.match(title):
        return None
    return f"the title must look like `type(scope): summary` with type in {', '.join(TYPES)}"


def cmd_sync(args: argparse.Namespace) -> int:
    try:
        pr = _pull_request(args)
    except (RuntimeError, ValueError, TypeError, OSError, KeyError) as exc:
        say(f"changelog: {exc}")
        return 2
    if pr.exempt:
        say(f"changelog: #{pr.number} is exempt (bot or `{SKIP_LABEL}` label), nothing to do.")
        return 0
    block = extract_block(pr.body)
    fix = f"uv run python scripts/changelog.py sync --pr {pr.number}"
    if not block.present or (not block.none and not block.bullets):
        say("changelog: the PR description needs a `## Changelog` block: bullets for the changes")
        say("users see, or `None` for an internal change. Edit the description, then run:")
        say(f"  {fix}")
        return 1
    if block.none:
        say(f"changelog: #{pr.number} declares `None`, no section needed.")
        return 0
    path = args.changelog or CHANGELOG
    text = path.read_text(encoding="utf-8")
    if args.check:
        problems = check_section(text, pr.number, pr.title, block.bullets)
        for problem in problems:
            say(f"changelog: {problem}")
        if problems:
            say(f"Fix with: {fix}  (then commit CHANGELOG.md)")
            return 1
        say(f"changelog: section #{pr.number} is up to date.")
        return 0
    new_text, status = upsert(text, pr.number, pr.title, block.bullets, args.date)
    if status != "unchanged":
        path.write_bytes(new_text.encode("utf-8"))
    say(f"changelog: section #{pr.number} {status}.")
    return 0


def cmd_title(args: argparse.Namespace) -> int:
    if args.event:
        try:
            pr = load_event(args.event)
        except (ValueError, TypeError, OSError) as exc:
            say(f"changelog: {exc}")
            return 2
        if pr.exempt:
            return 0
        title = pr.title
    elif args.commit_msg_file:
        lines = [
            ln
            for ln in Path(args.commit_msg_file).read_text(encoding="utf-8").splitlines()
            if not ln.startswith("#")
        ]
        title = lines[0].strip() if lines else ""
    else:
        title = args.text or ""
    reason = check_title(title)
    if reason is None:
        return 0
    say(f"changelog: {reason}.")
    say("Got:")
    say(quote(title))
    return 1


def cmd_lint(args: argparse.Namespace) -> int:
    text = (args.changelog or CHANGELOG).read_text(encoding="utf-8")
    version = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    errors = lint_text(text, version)
    for error in errors:
        say(f"changelog: {error}")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="write (or --check) the section of a pull request")
    sync.add_argument("--pr", type=int, help="PR number (default: the PR of the current branch)")
    sync.add_argument("--number", type=int, help="offline: PR number")
    sync.add_argument("--title", help="offline: PR title")
    sync.add_argument("--body-file", help="offline: file holding the PR description")
    sync.add_argument("--event", help="GitHub pull_request event file ($GITHUB_EVENT_PATH)")
    sync.add_argument("--check", action="store_true", help="verify only, change nothing")
    sync.add_argument("--date", help="YYYY-MM-DD for the section (default: keep, or today)")
    sync.add_argument("--changelog", type=Path, help=argparse.SUPPRESS)
    sync.set_defaults(func=cmd_sync)

    title = sub.add_parser("title", help="check a PR title / commit subject")
    title.add_argument("text", nargs="?")
    title.add_argument("--event", help="GitHub pull_request event file")
    title.add_argument("--commit-msg-file", help="commit message file (commit-msg hook)")
    title.set_defaults(func=cmd_title)

    lint = sub.add_parser("lint", help="validate the structure of CHANGELOG.md")
    lint.add_argument("--changelog", type=Path, help=argparse.SUPPRESS)
    lint.set_defaults(func=cmd_lint)
    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdout()
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
