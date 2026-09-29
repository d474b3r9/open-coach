"""Onboarding script: copy versioned templates to gitignored personal locations.

Run this once after a fresh clone. Idempotent: skips files that already exist
unless `--force` is passed. Stdlib only, no venv required.

Mappings (`--lang en`, the default):

  .claude/local.example/hooks.config.json          ->  .claude/local/hooks.config.json
  plans/.templates/athlete-profile.template.md     ->  plans/athlete-profile.md
  plans/.templates/training-journal.template.md    ->  plans/training-journal.md

With `--lang fr`, the French templates `athlete-profile.fr.template.md` and
`training-journal.fr.template.md` are copied instead. Destination names are
the same whatever the language.

Usage:

  uv run python scripts/setup_local.py             # create missing files (English)
  uv run python scripts/setup_local.py --lang fr   # use the French templates
  uv run python scripts/setup_local.py --force     # overwrite even if present
  uv run python scripts/setup_local.py --dry-run   # show what would be done
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from _console import ensure_utf8_stdout, utf8_print

REPO_ROOT = Path(__file__).resolve().parent.parent

LANGUAGES = ("en", "fr")

# Destination file names, identical for every template language.
ATHLETE_FILES = ("athlete-profile", "training-journal")


def build_mappings(lang: str = "en", repo_root: Path = REPO_ROOT) -> list[tuple[Path, Path]]:
    """Return the (template, destination) pairs for the given template language."""
    if lang not in LANGUAGES:
        raise ValueError(f"unsupported language {lang!r}, expected one of {LANGUAGES}")
    suffix = ".template.md" if lang == "en" else f".{lang}.template.md"
    templates = repo_root / "plans" / ".templates"
    mappings = [
        (
            repo_root / ".claude" / "local.example" / "hooks.config.json",
            repo_root / ".claude" / "local" / "hooks.config.json",
        ),
    ]
    mappings.extend(
        (templates / f"{name}{suffix}", repo_root / "plans" / f"{name}.md")
        for name in ATHLETE_FILES
    )
    return mappings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lang",
        choices=LANGUAGES,
        default="en",
        help="language of the athlete templates to copy (default: en)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite destination even if it already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be done without copying anything",
    )
    args = parser.parse_args()

    ensure_utf8_stdout()
    utf8_print("=" * 60)
    utf8_print("Setup local - open-coach")
    utf8_print("=" * 60)
    utf8_print(f"  REPO : {REPO_ROOT}")
    utf8_print(f"  LANG : {args.lang}")
    utf8_print("")

    created: list[Path] = []
    skipped: list[Path] = []
    overwrote: list[Path] = []
    missing_sources: list[Path] = []

    for src, dst in build_mappings(args.lang):
        if not src.exists():
            missing_sources.append(src)
            utf8_print(f"  [!] template missing : {src.relative_to(REPO_ROOT)}")
            continue

        if dst.exists() and not args.force:
            skipped.append(dst)
            utf8_print(f"  [=] already exists   : {dst.relative_to(REPO_ROOT)}")
            continue

        if args.dry_run:
            tag = "[would overwrite]" if dst.exists() else "[would create]"
            utf8_print(f"  {tag} {dst.relative_to(REPO_ROOT)}")
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if dst in skipped:
            skipped.remove(dst)
        if args.force and dst.exists() and dst.stat().st_size > 0:
            overwrote.append(dst)
            utf8_print(f"  [+] overwrote        : {dst.relative_to(REPO_ROOT)}")
        else:
            created.append(dst)
            utf8_print(f"  [+] created          : {dst.relative_to(REPO_ROOT)}")

    utf8_print("")
    utf8_print("-" * 60)
    if args.dry_run:
        utf8_print("Dry-run complete. No files were modified.")
    else:
        utf8_print(
            f"Done : {len(created)} created, "
            f"{len(overwrote)} overwrote, "
            f"{len(skipped)} skipped (already present)."
        )
    if missing_sources:
        utf8_print(
            f"WARNING : {len(missing_sources)} template(s) missing - the repo may be incomplete."
        )

    if not args.dry_run and (created or overwrote):
        utf8_print("")
        utf8_print("Next steps :")
        utf8_print(
            "  1. Open `plans/athlete-profile.md` and replace every <...> placeholder "
            "with your data."
        )
        utf8_print(
            "  2. Optionally edit `.claude/local/hooks.config.json` to watch extra "
            "markdown files with the journal-reminder hook."
        )
        utf8_print("  3. Run `uv run python scripts/audit_docs.py` to verify the repo state.")

    return 0 if not missing_sources else 1


if __name__ == "__main__":
    sys.exit(main())
