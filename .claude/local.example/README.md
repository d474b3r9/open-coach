# `.claude/local.example/` — versioned templates for personal config

This directory holds **templates** for the personal config files consumed by the hooks in `.claude/hooks/`. The directory itself is versioned. The runtime counterpart `.claude/local/` is **gitignored** and holds your actual values.

## Why this split exists

`.claude/hooks/` and `.claude/skills/` are versioned and **must remain free of personal data** (race names, targeted paces, athlete constraints, file paths specific to one user). Without that rule, a fork of this repo inherits someone else's training plan.

The hooks read `.claude/local/hooks.config.json` at runtime. If the file is absent or a key is missing, each hook falls back to safe generic defaults (see `CONTRIBUTING.md` § "Data separation policy" for the full rule).

## How to use

Run the onboarding script once after cloning the repo:

```powershell
# Windows
.\.venv\Scripts\python.exe scripts\setup_local.py
```

```bash
# bash / zsh
uv run python scripts/setup_local.py
```

This copies `hooks.config.json` from this directory to `.claude/local/` (creating the directory if needed) and seeds the personal markdown files in `plans/` from `plans/.templates/`. It is idempotent — re-running it skips files that already exist (use `--force` to overwrite).

Then edit `.claude/local/hooks.config.json` with your own values:

- `journal_reminder.extra_watched_filenames` — extra filenames outside `plans/` to watch for journal-update reminders. By default the hook already watches every `*.md` directly under `plans/` (excluding `.templates/`, `references/`, the journal itself, and `LEARNINGS.private.md`), so this list is rarely needed.

## Schema

Field types are illustrated in `hooks.config.json` in this directory. There is no JSON schema validation in v1 — typos are silent. If a hook seems not to fire, check your JSON syntax with `python -m json.tool .claude/local/hooks.config.json`.
