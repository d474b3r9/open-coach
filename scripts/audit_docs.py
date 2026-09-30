"""Consistency audit of the open_coach project's docs/skills/memory.

Checks performed:
1. memory/MEMORY.md ↔ files actually present in memory/
2. Consistency of the "X règles" / "X rules" rule-count claim between the
   frontmatter description and the number of "### Règle N" / "### Rule N"
   sections in memory files (French tokens kept for the author's memory)
3. entraineur SKILL.md — continuous numbering of "## N. ..." sections
4. LEARNINGS.md — continuous numbering + recap table matches the sections
5. Cross-references SKILL → LEARNINGS (cf #N) are all valid
6. No personal-data leak (home paths, emails, Drive IDs, secrets) in versioned files
7. No unexpected French in versioned text (the repo is English; intentional
   French is allowlisted or marked ``fr-ok``)

Usage: uv run python scripts/audit_docs.py

Stdlib only. No venv required.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from _console import ensure_utf8_stdout, utf8_print

REPO = Path(__file__).resolve().parent.parent


def _resolve_memory_dir() -> Path | None:
    """Locate the Claude Code memory dir for this project across OS variants.

    Resolution order:
    1. Env var ``OPEN_COACH_MEMORY_DIR`` (explicit override).
    2. Match the first subdir of ``~/.claude/projects/`` whose name contains
       both ``garmin`` and ``coach`` (case-insensitive). Claude Code encodes
       the project path into the dir name, which differs per machine and OS.
    3. ``None`` if nothing matches — Check 1 will warn rather than crash.
    """
    env = os.environ.get("OPEN_COACH_MEMORY_DIR") or os.environ.get("GARMIN_COACH_MEMORY_DIR")
    if env:
        return Path(env)
    root = Path.home() / ".claude" / "projects"
    if not root.exists():
        return None
    for d in sorted(root.iterdir()):
        if d.is_dir():
            n = d.name.lower()
            if "garmin" in n and "coach" in n:
                return d / "memory"
    return None


MEMORY_DIR = _resolve_memory_dir()
SKILL_FILE = REPO / ".claude" / "skills" / "entraineur" / "SKILL.md"
LEARNINGS_FILE = REPO / "LEARNINGS.md"


class Audit:
    def __init__(self) -> None:
        self.checks = 0
        self.warnings = 0
        self.errors = 0

    def ok(self, msg: str) -> None:
        self.checks += 1
        utf8_print(f"  [✓] {msg}")

    def warn(self, msg: str) -> None:
        self.checks += 1
        self.warnings += 1
        utf8_print(f"  [!] {msg}")

    def err(self, msg: str) -> None:
        self.checks += 1
        self.errors += 1
        utf8_print(f"  [✗] {msg}")


# ── Check 1: MEMORY.md ↔ files in memory/ ────────────────────────────────────


def check_memory_index(audit: Audit) -> None:
    utf8_print("\n--- Check 1: memory/MEMORY.md ↔ memory/*.md ---")

    if MEMORY_DIR is None or not MEMORY_DIR.exists():
        audit.warn(
            "memory dir not found (set OPEN_COACH_MEMORY_DIR or open the "
            "project once in Claude Code to create it). Skip."
        )
        return

    index_file = MEMORY_DIR / "MEMORY.md"
    if not index_file.exists():
        audit.err(f"MEMORY.md not found at {index_file}")
        return

    index_text = index_file.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\[[^\]]+\]\(([^)]+\.md)\)", index_text))
    actual = {p.name for p in MEMORY_DIR.glob("*.md") if p.name != "MEMORY.md"}

    missing = referenced - actual
    orphans = actual - referenced

    if missing:
        audit.err(f"MEMORY.md references {len(missing)} missing file(s): {sorted(missing)}")
    else:
        audit.ok(f"MEMORY.md → {len(referenced)} entries, all files exist")

    if orphans:
        audit.warn(f"{len(orphans)} unreferenced file(s) in memory/: {sorted(orphans)}")
    else:
        audit.ok("memory orphan check: 0 unreferenced files")


# ── Check 2: feedback_*.md frontmatter "X règles" consistency ────────────────


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_NRULES_RE = re.compile(r"(\d+)\s+(?:règles|rules)\b", re.IGNORECASE)
_RULE_HEADING_RE = re.compile(r"^###\s+(?:R[èe]gle|Rule)\s+(\d+)(?!\s*-)", re.MULTILINE)


def check_feedback_rules_count(audit: Audit) -> None:
    utf8_print("\n--- Check 2: feedback_*.md frontmatter ↔ number of Règle sections ---")

    if MEMORY_DIR is None or not MEMORY_DIR.exists():
        audit.warn("memory dir not resolvable, skip")
        return

    feedback_files = sorted(MEMORY_DIR.glob("feedback_*.md"))
    if not feedback_files:
        audit.warn("no feedback_*.md found")
        return

    for f in feedback_files:
        text = f.read_text(encoding="utf-8")

        # Extract frontmatter description
        fm_match = _FRONTMATTER_RE.match(text)
        if not fm_match:
            audit.warn(f"{f.name}: no frontmatter")
            continue
        fm = fm_match.group(1)
        desc_match = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
        if not desc_match:
            audit.warn(f"{f.name}: no description in frontmatter")
            continue

        desc = desc_match.group(1).strip()

        # Extract "N règles" claim from description and body
        claimed_in_desc = _NRULES_RE.findall(desc)
        body = text[fm_match.end() :]

        # Count actual "### Règle" sections
        rules = _RULE_HEADING_RE.findall(body)
        actual_n = len(rules)

        # If description claims a number, verify it
        if claimed_in_desc:
            claimed = int(claimed_in_desc[0])
            if claimed != actual_n:
                audit.err(
                    f"{f.name}: frontmatter says '{claimed} règles' "
                    f"but {actual_n} sections found ({rules})"
                )
            else:
                audit.ok(f"{f.name}: '{claimed} règles' matches {actual_n} sections")
        else:
            audit.ok(f"{f.name}: no rule count claim, {actual_n} sections found")


# ── Check 3: SKILL.md numbering ## N ─────────────────────────────────────────


_SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+", re.MULTILINE)


def check_skill_numbering(audit: Audit) -> None:
    utf8_print("\n--- Check 3: SKILL.md entraineur — continuous numbering ---")

    if not SKILL_FILE.exists():
        audit.err(f"SKILL.md not found: {SKILL_FILE}")
        return

    text = SKILL_FILE.read_text(encoding="utf-8")
    nums = [int(n) for n in _SECTION_RE.findall(text)]

    if not nums:
        audit.warn("SKILL.md: no numbered sections found")
        return

    # Accept either [1..N] or [0, 1..N] (a `## 0. ...` bootstrap section is allowed)
    start = nums[0] if nums[0] in (0, 1) else 1
    expected = list(range(start, max(nums) + 1))
    if nums == expected:
        audit.ok(f"SKILL.md sections: {start} → {max(nums)} continuous, no gap")
    else:
        gaps = set(expected) - set(nums)
        dups = [n for n in nums if nums.count(n) > 1]
        msg = f"SKILL.md: numbering issue. nums={nums}"
        if gaps:
            msg += f", gaps={sorted(gaps)}"
        if dups:
            msg += f", duplicates={sorted(set(dups))}"
        audit.err(msg)


# ── Check 4: LEARNINGS.md numbering + recap table ────────────────────────────


_LEARNING_HEADING_RE = re.compile(r"^###\s+(\d+)\.\s+", re.MULTILINE)
_LEARNING_TABLE_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|", re.MULTILINE)


def check_learnings(audit: Audit) -> None:
    utf8_print("\n--- Check 4: LEARNINGS.md — numbering + recap table ---")

    if not LEARNINGS_FILE.exists():
        audit.ok("LEARNINGS.md not present (gitignored / private), skip")
        return

    text = LEARNINGS_FILE.read_text(encoding="utf-8")

    # Find numbered headings (### N. ...)
    heading_nums = sorted({int(n) for n in _LEARNING_HEADING_RE.findall(text)})
    if not heading_nums:
        audit.warn("LEARNINGS.md: no numbered headings")
        return

    # Find numbers used in the recap table at the end (| N | ... | ... |)
    # Look only after "Severity legend" or last section
    legend_idx = text.find("## Severity legend")
    table_text = text[legend_idx:] if legend_idx > 0 else ""
    table_nums = sorted({int(n) for n in _LEARNING_TABLE_ROW_RE.findall(table_text)})

    # Continuous heading numbering
    expected = list(range(1, max(heading_nums) + 1))
    if heading_nums == expected:
        audit.ok(f"LEARNINGS.md headings: 1 → {max(heading_nums)} continuous")
    else:
        gaps = set(expected) - set(heading_nums)
        audit.err(f"LEARNINGS.md heading gaps: {sorted(gaps)}")

    # Headings ↔ table sync
    only_in_headings = set(heading_nums) - set(table_nums)
    only_in_table = set(table_nums) - set(heading_nums)
    if not only_in_headings and not only_in_table:
        audit.ok(
            f"LEARNINGS.md recap table: {len(table_nums)} rows match {len(heading_nums)} sections"
        )
    else:
        if only_in_headings:
            audit.err(f"LEARNINGS.md sections without table row: {sorted(only_in_headings)}")
        if only_in_table:
            audit.err(f"LEARNINGS.md table rows without section: {sorted(only_in_table)}")


# ── Check 5: cross-references SKILL → LEARNINGS ──────────────────────────────


_LEARNINGS_REF_RE = re.compile(r"LEARNINGS\s*#\s*(\d+)", re.IGNORECASE)


def check_cross_refs(audit: Audit) -> None:
    utf8_print("\n--- Check 5: cross-refs SKILL → LEARNINGS ---")

    if not SKILL_FILE.exists():
        audit.warn("skill file missing, skip cross-refs")
        return
    if not LEARNINGS_FILE.exists():
        audit.ok("LEARNINGS.md not present (gitignored / private), skip")
        return

    skill_text = SKILL_FILE.read_text(encoding="utf-8")
    learnings_text = LEARNINGS_FILE.read_text(encoding="utf-8")

    skill_refs = sorted({int(n) for n in _LEARNINGS_REF_RE.findall(skill_text)})
    learnings_nums = {int(n) for n in _LEARNING_HEADING_RE.findall(learnings_text)}

    if not skill_refs:
        audit.ok("SKILL.md: no LEARNINGS #N references")
        return

    invalid = [n for n in skill_refs if n not in learnings_nums]
    if invalid:
        audit.err(f"SKILL.md references invalid LEARNINGS #{invalid} (not found in LEARNINGS.md)")
    else:
        audit.ok(f"SKILL.md: {len(skill_refs)} LEARNINGS refs → all valid ({sorted(skill_refs)})")


# ── Check 6: personal-data leak in versioned files ──────────────────────────
# Grep structural markers of personal data in the versioned tree (gitignored
# paths such as plans/, .claude/local/, .venv/ are skipped automatically).
#
# The default list is STRUCTURAL ONLY: shapes that are personal by nature
# (home directories, real e-mail addresses, Google Drive folder IDs, inline
# secrets). It must never contain identifiers of a specific person — no name,
# nickname, city, club or race. Those belong in the environment variable
# ``OPEN_COACH_AUDIT_EXTRA_PATTERNS`` (CSV of regex patterns), which each
# maintainer sets on their own machine and never commits. This keeps the file
# safe to publish and the audit meaningful on every fork.
_DEFAULT_LEAK_PATTERNS = [
    # Absolute home directories (placeholders such as /home/you, C:\Users\you
    # and /Users/<user> are allowed).
    r"/home/(?!you\b|<)[a-z][a-z0-9_.-]*/",
    r"/Users/(?!you\b|<)[A-Za-z][A-Za-z0-9_.-]*/",
    r"[A-Z]:\\+Users\\+(?!you\b|<)[A-Za-z][A-Za-z0-9_.-]*\\",
    # Real e-mail addresses (example.com and GitHub noreply are placeholders).
    r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org)\b|users\.noreply\.github\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    # Google Drive folder IDs (long opaque IDs after /folders/ or in an env assignment).
    r"drive\.google\.com/drive/folders/[A-Za-z0-9_-]{20,}",
    r"(?:OPEN|GARMIN)_COACH_DRIVE_FOLDER_ID\s*=\s*[\"']?[A-Za-z0-9_-]{20,}",
    # Inline secrets: env credentials assigned to a literal instead of a placeholder.
    r"(?:GARMIN_PASSWORD|STRAVA_CLIENT_SECRET)\s*[=:]\s*[\"'](?![\"'$<]|your|xxx|\.\.\.)[^\"']{6,}",
    r"(?:oauth_token|oauth_token_secret|access_token|refresh_token)[\"']?\s*[=:]\s*[\"'][A-Za-z0-9._-]{16,}",
]

_EXTRA = os.environ.get("OPEN_COACH_AUDIT_EXTRA_PATTERNS") or os.environ.get(
    "GARMIN_COACH_AUDIT_EXTRA_PATTERNS", ""
)
_LEAK_PATTERNS = _DEFAULT_LEAK_PATTERNS + [p.strip() for p in _EXTRA.split(",") if p.strip()]

_LEAK_RE = re.compile("|".join(_LEAK_PATTERNS), re.IGNORECASE)

# Top-level paths to scan (relative to REPO) when git is unavailable. plans/ is
# gitignored and contains private data on purpose. The audit script scans
# itself too: its default patterns are structural, so they must not self-match.
_LEAK_SCAN_DIRS = [".claude", ".cursor", ".gemini", ".github", "docs", "scripts", "src", "tests"]
_LEAK_SCAN_GLOBS_ROOT = ["*.md", "*.toml", "*.json", "*.cfg", "*.ini", "*.yaml", "*.yml"]
# The pattern unit test holds deliberate fake leaks as fixtures.
_LEAK_EXCLUDE_FILES = {"test_audit_leak_patterns.py"}


def _iter_versioned_files() -> Iterator[Path]:
    """Yield (path) for each tracked or trackable file we want to scan.

    Uses `git ls-files --cached --others --exclude-standard` so that gitignored
    files (e.g. private LEARNINGS.md) are skipped automatically. Falls back to
    a directory walk if git is unavailable.
    """
    import subprocess

    text_exts = {
        ".md",
        ".py",
        ".sh",
        ".json",
        ".toml",
        ".cfg",
        ".ini",
        ".yaml",
        ".yml",
        ".txt",
        ".lock",
    }
    text_names = {".gitignore", ".python-version", "LICENSE"}

    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        result = None

    if result is not None:
        for rel in result.stdout.splitlines():
            if not rel.strip():
                continue
            p = REPO / rel
            if not p.is_file():
                continue
            if p.name in _LEAK_EXCLUDE_FILES:
                continue
            if p.suffix.lower() not in text_exts and p.name not in text_names:
                continue
            yield p
        return

    # Fallback when git is unavailable (no gitignore awareness)
    for d in _LEAK_SCAN_DIRS:
        root = REPO / d
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name in _LEAK_EXCLUDE_FILES:
                continue
            if p.suffix.lower() not in text_exts:
                continue
            yield p
    for pattern in _LEAK_SCAN_GLOBS_ROOT:
        for p in REPO.glob(pattern):
            if p.is_file():
                yield p


def check_personal_data_leak(audit: Audit) -> None:
    utf8_print("\n--- Check 6: personal-data leak in versioned files ---")

    leaks: list[tuple[str, int, str]] = []
    for path in _iter_versioned_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _LEAK_RE.search(line):
                rel = path.relative_to(REPO)
                snippet = line.strip()[:80]
                leaks.append((str(rel).replace("\\", "/"), lineno, snippet))

    if leaks:
        audit.err(f"{len(leaks)} personal-data leak(s) found in versioned files:")
        for rel_str, lineno, snippet in leaks[:20]:
            utf8_print(f"      {rel_str}:{lineno}: {snippet}")
        if len(leaks) > 20:
            utf8_print(f"      ... and {len(leaks) - 20} more")
    else:
        audit.ok("no personal-data leak in versioned files")


# ── Check 7: no French in versioned text ─────────────────────────────────────

# Accented letters plus frequent French words that are not English words.
_FRENCH_RE = re.compile(
    r"[àâçéèêëîïôûùüœ]"
    r"|\b(?:avec|pour|dans|sont|nous|vous|séance|semaine|allure|footing|renfo|coureur"
    r"|entraînement|sortie|récup)\b",
    re.IGNORECASE,
)
# Files that are French on purpose: the runtime string table, the French
# templates, test fixtures exercising French parsing, the changelog history,
# and this script (its check 2 matches the author's French memory files).
_FRENCH_EXCLUDE_PREFIXES = ("tests/",)
_FRENCH_EXCLUDE_FILES = {
    "src/open_coach/i18n.py",
    "scripts/audit_docs.py",
    "CHANGELOG.md",
}
_FRENCH_EXCLUDE_SUFFIXES = (".fr.template.md",)
# A line may keep French when it says so: bilingual skill triggers, glossary
# sections, explicit "French"/"legacy" mentions, or an inline `fr-ok` marker.
_FRENCH_LINE_ALLOW_RE = re.compile(r"^description:|\bfrench\b|\blegacy\b|fr-ok", re.IGNORECASE)
_MD_HEADING_RE = re.compile(r"^#{1,6}\s")


def find_french_lines(rel_path: str, text: str) -> list[tuple[int, str]]:
    """(line number, snippet) of unexpected French in one versioned file."""
    if (
        rel_path in _FRENCH_EXCLUDE_FILES
        or rel_path.startswith(_FRENCH_EXCLUDE_PREFIXES)
        or rel_path.endswith(_FRENCH_EXCLUDE_SUFFIXES)
    ):
        return []
    is_md = rel_path.endswith(".md")
    in_french_section = False
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if is_md and _MD_HEADING_RE.match(line):
            in_french_section = "french" in line.lower()
            continue
        if in_french_section or _FRENCH_LINE_ALLOW_RE.search(line):
            continue
        if _FRENCH_RE.search(line):
            hits.append((lineno, line.strip()[:80]))
    return hits


def check_no_french(audit: Audit) -> None:
    utf8_print("\n--- Check 7: no French in versioned text ---")

    hits: list[tuple[str, int, str]] = []
    for path in _iter_versioned_files():
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        if rel.startswith("plans/") and not rel.startswith("plans/.templates/"):
            continue  # personal data, gitignored in practice
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits.extend((rel, n, snippet) for n, snippet in find_french_lines(rel, text))

    if hits:
        audit.err(f"{len(hits)} French line(s) in versioned text (translate or mark fr-ok):")
        for rel, lineno, snippet in hits[:20]:
            utf8_print(f"      {rel}:{lineno}: {snippet}")
        if len(hits) > 20:
            utf8_print(f"      ... and {len(hits) - 20} more")
    else:
        audit.ok("no unexpected French in versioned text")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    ensure_utf8_stdout()

    utf8_print("=" * 60)
    utf8_print("Audit docs open_coach")
    utf8_print("=" * 60)
    utf8_print(f"  REPO   : {REPO}")
    utf8_print(f"  MEMORY : {MEMORY_DIR or '<not resolved — set OPEN_COACH_MEMORY_DIR>'}")

    audit = Audit()

    check_memory_index(audit)
    check_feedback_rules_count(audit)
    check_skill_numbering(audit)
    check_learnings(audit)
    check_cross_refs(audit)
    check_personal_data_leak(audit)
    check_no_french(audit)

    utf8_print("\n" + "=" * 60)
    utf8_print(f"Done: {audit.checks} checks | {audit.warnings} warnings | {audit.errors} errors")
    utf8_print("=" * 60)

    return 0 if audit.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
