# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

English-speaking runners can now use the project end to end; French stays
fully supported. The coach also runs from any MCP client (Cursor, Codex,
Gemini CLI, VS Code, Claude Desktop…), not only Claude Code.

### Added

- Any MCP client can run the coach: the operating rules (read the context
  first, methodology, watch sync, activity analysis, safety) are sent as MCP
  server instructions (`instructions.py`).
- Workflow guides exposed as MCP prompts (`onboard`, `plan-training`,
  `push-workout`, `analyze-run`, `daily-check`, `race-ready`), and every guide
  (methodology included) through the `get_coaching_guide` tool and
  `skill://<name>/SKILL.md` resources (official MCP Skills extension URIs,
  SEP-2640). The guide catalog (name + what/when) is embedded in the server
  instructions and in the `get_coaching_guide` description, so models pick
  the right guide unprompted. The wheel bundles the guides.
- `tests/test_skills_spec.py`: every skill is checked against the Agent
  Skills specification (frontmatter, size, one-level references, TOC).
- Read-only tools mirroring the resources, for clients that ignore MCP
  resources: `get_coaching_context`, `get_active_plan`, `get_archived_plan`.
- `next_steps` in the results of `generate_training_plan`,
  `save_training_plan` and `update_workout_completion` (watch sync, training
  journal, Drive sync when configured).
- `compact` parameter (default `True`) on `get_activity_details`,
  `get_training_status` and `list_watch_workouts`: drops empty fields and
  rounds floats in raw watch payloads.
- `open-coach` console script; project MCP configs for Cursor
  (`.cursor/mcp.json`) and Gemini CLI (`.gemini/settings.json`);
  `docs/mcp-clients.md` with setup for Codex, VS Code, Claude Desktop and others.
- `AGENTS.md`: agent-neutral repository guide (read by Codex, Cursor, Copilot,
  Gemini CLI); `CLAUDE.md` now imports it and keeps Claude Code specifics only.
- Language preference: `AthleteProfile.language` (`"en"` default, `"fr"`),
  set with `update_athlete_profile(language=...)`.
- Generated text (plan markdown, session descriptions, plan names) is
  rendered in English or French from the profile language (`i18n.py`).
- `plan_to_dsl` parses English block keywords (`incl.` / `including`)
  alongside the French `dont`.
- `strength` session type (canonical); `kiné-renfo` is kept as a legacy alias.
- English athlete templates `plans/.templates/athlete-profile.template.md`
  and `training-journal.template.md`; `scripts/setup_local.py --lang {en,fr}`
  picks the template language (default `en`).
- `fetch_transcript.py --lang {en,fr}` (extract-transcript skill) chooses the
  preferred caption language (default `en`).

### Changed

- The methodology skill is renamed `entraineur` → `coaching-rules`
  (`.agents/skills/coaching-rules/`, `skill://coaching-rules/...`), so every
  skill and guide name is English. The MCP guide name stays `rules`.

- `save_training_plan` accepts the plan as an object (full JSON schema
  published) or as a JSON string; `upload_workout` / `build_and_push_workout`
  accept a `DSLWorkout` object as well as JSON / text DSL.
- Skills moved to `.agents/skills/` (Agent Skills open standard, read
  natively by Codex, Gemini CLI, Cursor, Copilot); `.claude/skills` is a
  symlink to it for Claude Code. The workflow skills used to sit in `skills/`,
  where no client loaded them. They now name tools (`get_coaching_context`,
  `get_coaching_guide`) instead of bare `coach://` reads.
- Skill frontmatter follows the spec: `version` moved under `metadata`,
  `compatibility` added, descriptions rewritten (third person, what + when,
  EN/FR triggers, vendor-neutral). Long references gained a `## Contents`
  section; `plan-training` and `push-workout` open with a checklist.
- `get_activity_details`, `get_training_status`, `list_watch_workouts` return
  compacted payloads by default (`compact=False` restores the raw payload).
- **Licence**: Open Coach is now free software under the **AGPL-3.0**
  (was PolyForm Noncommercial 1.0.0), dual-licensed with optional commercial
  terms from the maintainer. Contributors accept a CLA (`CLA.md`) once, via
  a bot on their first pull request.
- Community files: `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1),
  `SECURITY.md`, issue templates (bug, feature, new watch platform) and a
  pull request template; CONTRIBUTING.md starts with how to contribute.
- The default rclone remote for Drive sync is `gdrive`; set
  `OPEN_COACH_DRIVE_REMOTE` if yours is named differently.
- **Breaking**: the project is renamed **Open Coach** (it is no longer tied
  to Garmin, nor to running only). Package `garmin_coach` → `open_coach`, MCP
  server `garmin-coach` → `open-coach` (tool prefix `mcp__open-coach__`),
  data directory `~/.garmin-coach/` → `~/.open-coach/`, env vars
  `GARMIN_COACH_*` → `OPEN_COACH_*`. Existing installs keep working: the data
  directory is moved automatically on first use (never when both exist), and
  the legacy `GARMIN_COACH_*` variables are still read, with a hint to rename
  them. `GARMIN_EMAIL` / `GARMIN_PASSWORD` and the `~/.garth` token cache are
  Garmin credentials and keep their names.
- **Breaking**: watch tools no longer carry the Garmin name:
  `list_watch_workouts`, `schedule_watch_workout`, `unschedule_watch_workout`,
  `delete_watch_workout`, `clean_watch_calendar`, `purge_watch_workouts`
  (formerly `*_garmin_*`). `archive_active_plan(cleanup_garmin=…)` becomes
  `cleanup_watch`, and its `garmin_cleanup` result key `watch_cleanup`.
- Athlete files renamed: `plans/fiche-coureur.md` → `plans/athlete-profile.md`
  and `plans/journal-coureur.md` → `plans/training-journal.md`. The French
  templates are now `*.fr.template.md`. Rename your existing files by hand
  when upgrading.
- Repository translated to English: docs, skills, hooks, scripts, comments
  and docstrings.
- `sync_upcoming_workouts` pushes only sessions that carry quality (tempo,
  intervals, race, long runs with an embedded pace block); plain easy /
  recovery / long runs are listed in `left_unpushed`. Pass
  `include_easy=True` for the previous behaviour.

- Watch access goes through a `WatchProvider` interface (`providers/`), with
  Garmin as the only implementation so far (`GARMIN_COACH_WATCH`, default
  `garmin`). Groundwork for other watches (COROS); tool names and outputs are
  unchanged. The workout registry records each upload's `provider`.

### Fixed

- `coach://context`, race predictions / readiness / pacing and plan
  generation judged current form from the CTL/ATL/TSB stored at the last
  bootstrap (months old). They now use today's load from the watch;
  `coach://context` exposes it as `training_load` with its date and source,
  and no longer shows the stale values in `profile`. Load windows default to
  180 days (90 days understated CTL by ~20 %).
- `get_training_load` reported CTL/ATL/TSB on the last activity date: after
  a week off, the fatigue of the last block still showed as today's. The load
  is now computed as of today, rest days included (`as_of` in the output).
- `get_recovery_status` / `get_adaptive_recommendation` used the TSB of the
  profile snapshot (last bootstrap, possibly months old); they now compute it
  from the watch history on the assessed day, the profile being a fallback.
  Missing HRV / sleep / stress / feedback no longer produce alarming advice,
  a good measured signal is never "the main concern", and the assessment is
  dated with the requested day.
- `get_training_status` always returned `None` for VO2max, training status
  and readiness: garminconnect was called with `0` / `"running"` instead of
  a `YYYY-MM-DD` date and raised `ValueError`. Today's date is now passed.
- HRV averages are read from garminconnect's `hrvSummary` (top-level keys
  kept as a fallback).
- `generate_plan` dropped the race week: a race falling after the last full
  week was outside the plan, with no race session. The race week is now
  included and race day carries a `race` session at target (or predicted) pace.
- Generated tempo sessions could not be pushed by `sync_upcoming_workouts`,
  and generated intervals were pushed without their 400 m recoveries.

## [0.2.0] - 2026-09-21

Public-release hardening. Breaking changes are listed under **Changed**.

### Added

- Structural personal-data audit: `scripts/audit_docs.py` default patterns
  are shapes only (home paths, e-mails, Drive IDs, inline secrets); person
  markers stay in `GARMIN_COACH_AUDIT_EXTRA_PATTERNS`. The script scans
  itself, shell scripts and lockfiles, with a unit test per pattern.
- `env_credential()` in `auth.py`: an unexpanded `${VAR}` or `<placeholder>`
  passed through `.mcp.json` counts as unset, so the server starts offline
  instead of firing a Garmin SSO login with garbage.
- `plan_metrics.recompute_week_actuals`: completion rate excludes rest and
  strength sessions; `TrainingWeek.extra_activities` sums into weekly volume.
- `parse_iso_date` / `invalid_date_error` helpers; every tool that takes a
  date string now soft-fails on a malformed value.
- Drive sync mass-delete guards split by rclone semantics
  (`GARMIN_COACH_BISYNC_MAX_DELETE_PCT`, `GARMIN_COACH_OBSIDIAN_MAX_DELETE`).
- `scripts/garmin_re_auth.py` checks its optional dependencies up front and
  points to `uv sync --extra reauth`.

- `plan_to_dsl.convert_planned_workout`: description-driven plan → DSL parser
  (sets `N×D @ pace r rec`, embedded `dont N min/km @ M`, zone letters resolved
  from the profile VDOT). `sync_upcoming_workouts` reports sessions it cannot
  parse under `not_converted` instead of pushing a guessed structure.
- `build_running_workout` appends an open-ended (lap-button) cooldown when the
  DSL does not already end on one — every pushed workout now finishes on a lap
  press, never on an automatic stop (entraineur DSL Rule D).
- `save_training_plan` now refreshes the plan markdown copy (returns
  `markdown_path`), same soft-fail contract as the other plan writers.
- Ruff rule set (E/F/I/B/UP/N/C4/SIM/RUF + PT/ARG/ASYNC) and mypy across the
  codebase; `ruff format` enforced; CI workflow + pre-commit hooks at parity.
- +150 tests: MCP tool handlers, models, and the I/O boundary
  (auth, Strava auth/client, plan renderer, server lifespan).
- Plan lifecycle: `rename_active_plan`, auto-archive of expired plans,
  `archive_active_plan` with Garmin calendar cleanup.
- HR zones (Karvonen) merged into `get_training_zones` from profile HR.
- Session-duration constraints (`max_weekday_minutes`/`max_weekend_minutes`)
  enforced by the plan generator; active injuries and constraint notes
  surfaced by `generate_training_plan`; new `resolve_injury` tool.
- Compact text DSL accepted by `upload_workout`/`build_and_push_workout`.
- `coach://plans/archive/{name}` resource to read an archived plan back.
- Planned-vs-actual auto-fill in `record_workout_feedback`.
- CTL-based endurance penalty in half/marathon race predictions.

### Changed

- `sync_upcoming_workouts` no longer builds quality sessions from a
  `total − 3.5 km at target pace` heuristic (a `10 km dont 15 min @ M` session
  was pushed as a single 7.5 km M-pace block on 2026-09-10). Steady runs are
  one block (Rule A); quality sessions get lap-button warmup/cooldown (Rule B).
- Unified tool error contract: every tool soft-fails with `{"error": ...}`
  (no more raised RuntimeError or list-wrapped errors);
  `get_recent_runs` now returns `{"activities": [...], "count": n}`.
- `schedule_garmin_workout`/`build_and_push_workout` parameter `date`
  renamed to `target_date`.
- `upload_workout`, `build_and_push_workout` and `save_training_plan` return
  `{"error": ...}` on malformed input instead of raising.
- `unschedule_garmin_workout` carries `destructiveHint`.
- Hooks in `.claude/settings.json` invoke `python3`.
- `.mcp.json` variables use `${VAR:-}` defaults.
- Activity cache persisted in a versioned envelope (legacy bare list
  still readable); Pydantic constraints on profile physiology fields.
- `uv.lock` committed; dev dependencies moved to `[dependency-groups]`
  (plain `uv sync` now installs them — CI previously installed nothing).

### Removed

- Dead code: `OnboardingState`, `WorkoutSyncState`, `GarminAPIError`,
  `StravaClient.get_athlete`, `WorkoutFeedback.adjustment_made`,
  `scripts/test_connection.py` (superseded by `scripts/smoke_mcp.py`).
- Author-specific values from versioned files: race-name audit patterns,
  home-town activity names in docs and tests, real physiology and injury
  history in the athlete profile template.
- `.claude-plugin/plugin.json` and every mention of a Claude Code plugin:
  the repo is a project you open as a workspace, not an installable
  package (state lives in `<repo>/plans/`, hooks assume the repo is the
  workspace).

## [0.1.0] - 2026-05-13

Initial public release.

### Added

- FastMCP server exposing Garmin Connect tools (`get_recent_runs`,
  `get_activity_details`, `get_recovery_status`, `get_race_predictions`, …).
- Pure-computation layer: `vdot.py`, `zones.py`, `training_load.py` (CTL/ATL/TSB),
  `workout_dsl.py` + `workout_builder.py`, `plan_generator.py`,
  `race_predictor.py`, `recovery_monitor.py`, `plan_renderer.py`.
- Two-layer skill architecture: `entraineur` (methodology rules) + workflow
  skills (`onboard`, `plan-training`, `push-workout`, `analyze-run`,
  `daily-check`, `race-ready`).
- Strava integration as read-only fallback (`get_strava_activities`).
- Optional Google Drive sync via `rclone` (`scripts/drive_sync.sh`).
- Garmin SSO recovery script (`scripts/garmin_re_auth.py`) using SeleniumBase UC
  + DI exchange for Cloudflare-resistant login.
- Pre-commit audit (`scripts/audit_docs.py`) for personal-data leak detection.
- Comprehensive test suite covering the pure-computation modules.

### Notes

This is a personal-tooling project published as-is. Forks are encouraged for
your own use, but no compatibility guarantees are made between versions while
the project is in beta (`0.x`).
