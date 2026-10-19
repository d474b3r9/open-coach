# Changelog

All notable changes to this project are documented in this file, **one section
per pull request**, newest first. The heading carries the pull request number,
its title and the date it was merged. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) in spirit, but is
organised by change rather than by version. A release is a section of its own,
headed by its version; the current one is `version` in `pyproject.toml`. The
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(`0.x`: breaking changes are possible and are flagged **Breaking**).

To add an entry, see "Changelog" in [CONTRIBUTING.md](CONTRIBUTING.md).

## #26 — feat(state): restore the coach on another machine from a portable snapshot (2026-10-19)

- Move the coach between machines, Windows ⇄ Linux ⇄ macOS: the state (profile,
  goals, constraints, plans, feedback, watch uploads) is mirrored into
  `plans/.state/` on every save (portable UTF-8 JSON) and carried by the Drive
  sync.
- `restore_coach_state` previews then imports it (newer file wins, feedback
  merged, nothing overwritten without `force`); `export_coach_state` writes it on
  demand; the `restore-coach` workflow guides the whole move.
- A machine that never restored an existing snapshot cannot overwrite it. Opt
  out with `OPEN_COACH_STATE_SNAPSHOT=off`.

## #25 — fix(core): store UTC and write UTF-8 on every platform (2026-10-19)

- One time convention on every OS: stored instants (`created_at`, `updated_at`,
  feedback and upload times…) are UTC (`...Z`), shown in the PC's local time
  (plan markdown), and "today" is the PC's local calendar day. `clock.py` is the
  only place that reads the system clock (enforced by a test). Older files with
  naive times are read as local time and rewritten as UTC on the next save.
- Coach JSON files are written as UTF-8 on every platform (they used the locale
  encoding, cp1252 on Windows, so a file moved to Linux was unreadable). Legacy
  cp1252 files still load and are rewritten as UTF-8.

## #24 — docs(drive-sync): move the optional guide to docs/optional, add Windows notes (2026-10-19)

- The optional Google Drive / Obsidian guide moved to `docs/optional/drive-sync.md`
  (linked from the README), with Windows notes: `rclone` on `PATH`, Git Bash instead
  of WSL `bash`, OAuth client and consent screen, per-machine paths.

## #23 — fix(scripts): await coach:// resources in smoke_mcp (2026-10-19)

- `scripts/smoke_mcp.py` read the `coach://` resources without awaiting them
  and without a request context, so every resource reported "non-string or
  empty". It now unwraps the FastMCP-wrapped function and awaits it.

## #22 — docs(readme): update architecture diagram (2026-10-07)

- README architecture diagram redrawn: watch provider layer, sport-agnostic core
  and sport plugins, Agent Skills (`coaching-rules`, `coaching-rules-running`, the
  workflow guides), server instructions, auto-migrated JSON state.

## #21 — chore(repo): move code of conduct and security policy to .github/ (2026-10-02)

- `CODE_OF_CONDUCT.md` and `SECURITY.md` moved to `.github/`, where GitHub still
  detects them; links in the README and `CONTRIBUTING.md` follow.

## #20 — docs(contributing): document issue, epic and sub-issue workflow (2026-10-01)

- CONTRIBUTING documents issues, epics and sub-issues (`good first issue`,
  `help wanted`, `Closes #<sub-issue>`, `Part of #<epic>`); new "Part of an
  epic" issue template and a linked-issue line in the pull request template.

## #10 — feat(coaching): per-day duration caps, injury check-in, session adjustments (2026-10-01)

- Per-day duration caps: `TrainingConstraints.max_minutes_by_day` (for example
  `{"monday": 45}`) overrides the weekday / weekend cap for that day, and
  `set_training_constraints` takes it. A day capped under 60 minutes gets an
  easy run; the long run and the quality session go to a longer day when one
  exists. Optional field, existing files load unchanged.
- Injury check-in after a session: `update_workout_completion` and
  `record_workout_feedback` return `active_injuries` and a `next_steps` entry
  asking how each injury felt (`resolve_injury` or `report_injury`).
- `adjust_planned_workout` tool: changes one session of the active plan (type,
  description, distance, duration, intensity) and records why
  (`PlannedWorkout.adjustment_note`); the daily-check workflow uses it when the
  athlete accepts an adjustment.

## #9 — feat(sports): running as a plugin behind the Sport protocol (2026-09-30)

- Running is a plugin behind the `Sport` protocol (`sports/running/`: VDOT, zones,
  profile, plan generator, plan to DSL, race predictions, recovery adaptation,
  i18n); `periodization.py` is shared by every sport's plan builder.
- Guards: `tests/test_sport_isolation.py`, `test_sport_contract.py` and a
  fake-sport test. `AGENTS.md` gains "Sport plugins" and "Adding a sport".
- `coaching-rules-running` skill with the running rules, and
  `references/principles.md` (80/20, CTL progression, recovery weeks) in the
  universal guide.
- **Breaking**: `calculate_vdot_from_race` is `calculate_fitness_from_race`,
  `get_training_zones(vdot=…)` is `get_training_zones(sport=…, fitness=…)`, the
  bootstrap output has one block per sport, and the guide topics
  `methodology` / `dsl-conventions` / `anti-patterns` are `running-methodology`
  / `running-dsl-conventions` / `running-anti-patterns`.

## #8 — feat(sports): sport-agnostic watch I/O and workout DSL (2026-09-30)

- Activities of every sport: `WatchProvider.list_activities(start, end, sports)`
  with a vendor-neutral `Activity` (`sport`, `vendor_type`); Garmin maps its
  activity types.
- CTL/ATL/TSB count every activity with heart rate (bike, swim and strength
  sessions were ignored before).
- The workout DSL carries a required `sport` and pace or heart-rate targets
  (`@ 140-150bpm` in text).
- **Breaking**: `get_recent_runs` is `get_recent_activities(sport=None)`,
  `vdot_override` is `fitness_override`, the DSL JSON uses `target` (with `kind`)
  instead of `pace` and requires `sport` (text DSL needs `sport=`).

## #7 — feat(sports): sport-agnostic persisted models with schema migrations (2026-09-30)

- Sport-agnostic core: the `sports/` package (`Sport` protocol, neutral types,
  registry) and schema v2 for the persisted files (distances in metres, durations
  in seconds, `Intensity` targets, per-sport volume, fitness and records, `sport`
  on goals, sessions and feedback).
- `migrations.py` upgrades older files on read and keeps the original once as
  `<file>.v1.bak`.
- **Breaking** (persisted data migrates on first read): `update_workout_completion`
  takes `actual_distance_m` and `actual_duration_s` instead of
  `actual_distance_km`; `generate_training_plan` returns `start_volume` /
  `peak_volume` as strings (`"42 km"`); `record_workout_feedback` defaults
  `workout_type` to the planned session type; `set_training_goal` gains `sport`;
  the plan markdown column "Pace" is now "Target".

## #4 — fix(audit): drop obsolete SKILL.md numbered-sections check (2026-09-30)

- `scripts/audit_docs.py` no longer warns "no numbered sections found": the check
  for `## N.` sections in the methodology `SKILL.md` is removed, since the rules
  moved to named sections in `references/`.

## #3 — refactor(skills): rename entraineur skill to coaching-rules (2026-09-30)

- **Breaking**: the methodology skill `entraineur` is renamed `coaching-rules`
  (`skill://coaching-rules/...`), so every skill and guide name is English.
  The MCP guide name stays `rules`.

## #2 — feat(skills): follow the Agent Skills standard and serve skills over MCP (2026-09-30)

- Skills follow the Agent Skills standard and are served over MCP as
  `skill://<name>/SKILL.md` resources (official MCP Skills extension, SEP-2640),
  and through the `get_coaching_guide` tool. The guide catalog (name + what/when)
  is embedded in the server instructions and in the tool description, so models
  pick the right guide unprompted. The wheel bundles the guides.
- `tests/test_skills_spec.py`: every skill is checked against the Agent Skills
  specification (frontmatter, size, one-level references, table of contents).
- Skill frontmatter follows the specification (`version` under `metadata`,
  `compatibility`, third-person descriptions with English and French triggers);
  long references gained a `## Contents` section; `plan-training` and
  `push-workout` open with a checklist.
- **Breaking**: skills live in `.agents/skills/`; `.claude/skills` is a symlink
  for Claude Code (on Windows it needs `git config core.symlinks true`).
  `coach://guide/{name}` is removed: use `skill://<name>/SKILL.md` or
  `get_coaching_guide`.

## #1 — feat: make the coach usable from any MCP client, not only Claude Code (2026-09-30)

- The coach runs from any MCP client (Cursor, Codex, Gemini CLI, VS Code, Claude
  Desktop…): the operating rules (read the context first, methodology, watch
  sync, activity analysis, safety) are sent as MCP server instructions
  (`instructions.py`).
- Workflow guides exposed as MCP prompts (`onboard`, `plan-training`,
  `push-workout`, `analyze-run`, `daily-check`, `race-ready`).
- Read-only tools mirroring the resources, for clients that ignore MCP
  resources: `get_coaching_context`, `get_active_plan`, `get_archived_plan`.
- `next_steps` in the results of `generate_training_plan`, `save_training_plan`
  and `update_workout_completion` (watch sync, training journal, Drive sync when
  configured).
- `save_training_plan` accepts the plan as an object (full JSON schema published)
  or as a JSON string; `upload_workout` and `build_and_push_workout` accept a
  `DSLWorkout` object as well as JSON or text DSL.
- `open-coach` console script; project MCP configs for Cursor
  (`.cursor/mcp.json`) and Gemini CLI (`.gemini/settings.json`);
  `docs/mcp-clients.md` with setup for Codex, VS Code, Claude Desktop and others.
- `AGENTS.md`: agent-neutral repository guide (read by Codex, Cursor, Copilot,
  Gemini CLI); `CLAUDE.md` imports it and keeps Claude Code specifics only.
- **Breaking**: `get_activity_details`, `get_training_status` and
  `list_watch_workouts` return compacted payloads by default (`compact=False`
  restores the raw payload; the new `compact` parameter drops empty fields and
  rounds floats). The workflow skills moved out of `skills/`, where no client
  loaded them, and now name tools instead of bare `coach://` reads.

## 0.2.0 — Initial public release (2026-09-29)

The project goes public on the day this repository is created. This entry folds
in everything built before, in private (`0.1.0` of 2026-05-13, the initial
commit, and `0.2.0` of 2026-09-21), and the work done to open the project:
English documentation, the licence, the rename and the community files.

### Added

- FastMCP server exposing the watch and coaching tools (recent activities,
  activity details, recovery status, race predictions, training load and zones,
  plan generation and lifecycle, workout upload and scheduling…), with Garmin
  Connect as the only watch behind a `WatchProvider` interface (`providers/`),
  groundwork for other watches. The workout registry records each upload's
  `provider`.
- Pure-computation layer: VDOT and Daniels zones, Karvonen heart-rate zones,
  training load (CTL/ATL/TSB), the workout DSL and its Garmin builder, plan
  generator, race predictor (with a CTL-based endurance penalty for half and
  marathon), recovery monitor, plan renderer and plan metrics (completion rate
  ignores rest and strength sessions; extra activities add to weekly volume).
- Two-layer skill architecture: the methodology rules plus the workflow skills
  (`onboard`, `plan-training`, `push-workout`, `analyze-run`, `daily-check`,
  `race-ready`).
- Plan lifecycle: `rename_active_plan`, auto-archive of expired plans,
  `archive_active_plan` with watch calendar cleanup, `coach://plans/archive/{name}`,
  planned-versus-actual auto-fill in `record_workout_feedback`.
- Session-duration constraints (`max_weekday_minutes`, `max_weekend_minutes`)
  enforced by the plan generator; active injuries and constraint notes shown by
  `generate_training_plan`; `resolve_injury`.
- `plan_to_dsl.convert_planned_workout`: reads a plan session description (sets
  `N×D @ pace r rec`, embedded `dont` / `incl.` blocks, zone letters from the
  profile VDOT) and refuses rather than guessing; `sync_upcoming_workouts`
  reports what it could not convert under `not_converted`. Every pushed workout
  ends on an open-ended (lap-button) cooldown. Compact text DSL accepted by
  `upload_workout` and `build_and_push_workout`.
- Strava integration as a read-only fallback (`get_strava_activities`).
- Optional Google Drive / Obsidian sync via `rclone` (`scripts/drive_sync.sh`),
  with mass-delete guards split by rclone semantics.
- Garmin SSO recovery script (`scripts/garmin_re_auth.py`, SeleniumBase UC + DI
  exchange, Cloudflare-resistant) that checks its optional dependencies up front.
- `env_credential()`: an unexpanded `${VAR}` or `<placeholder>` passed through
  `.mcp.json` counts as unset, so the server starts offline instead of firing a
  Garmin login with garbage. `parse_iso_date` / `invalid_date_error`: every tool
  that takes a date soft-fails on a malformed value.
- English and French: `AthleteProfile.language` (set with
  `update_athlete_profile(language=...)`) drives the generated text (plan
  markdown, session descriptions, plan names; `i18n.py`); English athlete
  templates and `scripts/setup_local.py --lang {en,fr}`;
  `fetch_transcript.py --lang {en,fr}`; the plan parser reads `incl.` and `dont`;
  the `strength` session type (`kiné-renfo` stays a legacy alias).
- Quality gates: structural personal-data audit (`scripts/audit_docs.py`: home
  paths, e-mails, Drive IDs, inline secrets), ruff (E/F/I/B/UP/N/C4/SIM/RUF +
  PT/ARG/ASYNC) and mypy across the codebase, `ruff format` enforced, CI and
  pre-commit at parity, `uv.lock` committed, and a test suite covering the tool
  handlers, models and the I/O boundary.
- Community files: `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md`,
  issue templates (bug, feature, new watch platform) and a pull request template;
  CONTRIBUTING starts with how to contribute.

### Changed

- **Licence**: free software under the **AGPL-3.0** (was PolyForm Noncommercial
  1.0.0), dual-licensed with optional commercial terms from the maintainer.
  Contributors accept a CLA (`CLA.md`) once, through a bot on their first pull
  request.
- The repository is in English: docs, skills, hooks, scripts, comments and
  docstrings.
- `sync_upcoming_workouts` pushes only sessions that carry quality (tempo,
  intervals, race, long runs with an embedded pace block); plain easy, recovery
  and long runs are listed in `left_unpushed` (`include_easy=True` restores the
  previous behaviour). Steady runs are one block and quality sessions get
  lap-button warm-up and cool-down.
- Every tool soft-fails with `{"error": ...}`, including on malformed input.
  `get_recent_activities` returns `{"activities": [...], "count": n}`;
  `schedule_watch_workout` and `build_and_push_workout` take `target_date`.
- The activity cache is stored in a versioned envelope (the legacy bare list
  stays readable); profile physiology fields have Pydantic constraints.

### Fixed

- Current form is judged from today's load, not from a months-old snapshot:
  `coach://context`, race predictions, readiness, pacing and plan generation use
  the CTL/ATL/TSB computed from the watch (`training_load` with its date and
  source; load windows default to 180 days, 90 days understated CTL by about
  20 %). `get_training_load` is computed as of today, rest days included
  (`as_of`). `get_recovery_status` and `get_adaptive_recommendation` compute the
  TSB on the assessed day; missing HRV, sleep, stress or feedback no longer give
  alarming advice.
- `get_training_status` returned `None` for VO2max, training status and
  readiness (garminconnect was called without a date); HRV averages are read
  from `hrvSummary`.
- `generate_plan` dropped the race week; it is now included and race day carries
  a `race` session at the target (or predicted) pace. Generated tempo sessions
  can be pushed by `sync_upcoming_workouts`, and generated intervals keep their
  400 m recoveries.

### Notes

- **Coming from the private builds**: the project is renamed **Open Coach**
  (no longer tied to Garmin nor to running only). Package `garmin_coach` →
  `open_coach`, MCP server `garmin-coach` → `open-coach` (tool prefix
  `mcp__open-coach__`), data directory `~/.garmin-coach/` → `~/.open-coach/`,
  env vars `GARMIN_COACH_*` → `OPEN_COACH_*`. Existing installs keep working:
  the data directory is moved automatically on first use (never when both
  exist) and the legacy variables are still read, with a hint to rename them.
  `GARMIN_EMAIL`, `GARMIN_PASSWORD` and the `~/.garth` token cache are Garmin
  credentials and keep their names.
- Watch tools no longer carry the Garmin name: `list_watch_workouts`,
  `schedule_watch_workout`, `unschedule_watch_workout`, `delete_watch_workout`,
  `clean_watch_calendar`, `purge_watch_workouts`; `archive_active_plan` takes
  `cleanup_watch` and returns `watch_cleanup`.
- Athlete files are `plans/athlete-profile.md` and `plans/training-journal.md`
  (formerly `fiche-coureur.md` and `journal-coureur.md`; the French templates
  are `*.fr.template.md`). Rename existing files by hand. The default rclone
  remote is `gdrive` (`OPEN_COACH_DRIVE_REMOTE` to change it).
- Removed from the private builds: dead code (`OnboardingState`,
  `WorkoutSyncState`, `GarminAPIError`, `StravaClient.get_athlete`,
  `scripts/test_connection.py`), author-specific values in versioned files, and
  the Claude Code plugin manifest (the repository is a project you open as a
  workspace, not an installable package).
- Beta: no compatibility guarantees between `0.x` versions.
