# AGENTS.md

Guidance for any AI agent working in this repository — Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot… — focused on the coaching operating rules, architecture, gotchas, and how to extend. Coaching domain rules live in the `entraineur` guide (`.claude/skills/entraineur/`, also served over MCP by `get_coaching_guide`); project policies live in `CONTRIBUTING.md`. `CLAUDE.md` imports this file and only adds Claude Code specifics.

**Portability rule**: this file only reaches agents that read `AGENTS.md`. Anything an agent *must* do while coaching also has to reach MCP-only clients (Claude Desktop, ChatGPT, …): put it in the server instructions (`src/open_coach/instructions.py`), in a tool's `next_steps` (`tools/_common.plan_update_next_steps`), or in a guide under `.claude/skills/`. See "Client portability" below.

## Watch sync after plan update (any AI agent)

The server repeats these rules to every client (instructions + `next_steps`); keep both in sync with this section.

After any call to `save_training_plan`, automatically push new or modified workouts to the watch platform — no confirmation needed. Mandatory sequence:
1. Call `list_watch_workouts` to see what is already scheduled for ALL affected dates (old and new).
2. For any existing workout found at an old or conflicting date: call `unschedule_watch_workout` (and `delete_watch_workout` if it was created by this coach) before proceeding.
3. Push the new/moved workouts via `build_and_push_workout`.
4. Skip `rest` and `strength` entries (legacy name `kiné-renfo`) — no watch workout for those.
5. **Push only workouts that carry quality or a pace block.** Push: `interval`, `tempo`, `race`, and any `long_run` whose description contains a pace block (`incl. 6 km @ M`, `dont 25 min @ M`). **Never push an easy run (EF, *endurance fondamentale*)** — even with strides or strength appended — nor a plain easy long run (single pace, no block). The athlete runs those freely on feel; a structured workout on the watch for an easy run is noise.
6. Briefly report what was unscheduled, what was pushed, and what was intentionally left unpushed.

## Drive/Obsidian sync after plan update (any AI agent)

After any change to the active plan or its markdown copies — `save_training_plan`, `update_workout_completion`, `generate_training_plan`, `rename_active_plan`, `archive_active_plan`, or a direct edit of a file under `plans/` (plan, `training-journal.md`, `athlete-profile.md`) — automatically run the Drive sync so the Obsidian mirror is refreshed. No confirmation needed.

1. Append the journal entry to `plans/training-journal.md` **first** (session and/or decision), so it ships in the same sync.
2. Run `bash scripts/drive_sync.sh --all` (repo `plans/` ↔ Drive bisync, then Drive → Obsidian pull). Requires the `OPEN_COACH_*` env vars listed below; if they are missing, say so and give the command instead of failing silently.
3. Report the rclone outcome in one line (files transferred, conflicts as `*.conflict-*`, or the error text).
4. Never run `--init-project` / `--init-obsidian` automatically — those rebaseline and need explicit user consent.

## Activity analysis rules (any AI agent)

These rules apply to any analysis of Garmin activities — regardless of model or tool used.

1. **Raw timestamps when same-day activities**: show exact start times and compute the gap explicitly. Never infer "morning/afternoon split" without checking.
2. **Separate columns for actual activity vs planned workout**: never silently merge them. Keep two distinct entries until the match is explicitly validated.
3. **Use Garmin activity name as label**: the raw name as Garmin records it (`Riverside Running`, or on a French-locale watch `Riverside Course à pied`; `Forest Trail`) — never replace it with the plan description (`Easy run`, `Easy + strength`).
4. **Unmatched activities are orphans**: if an activity has no `completed: true` counterpart in the active plan, list it as "not matched in plan" — do not auto-map to the nearest planned session.

## Dev commands

```bash
uv sync                               # Install dependencies (dev group included)
uv run pytest                         # All tests
uv run pytest tests/test_vdot.py -v   # Single test file
uv run pytest -k "test_pace"          # Filter by name
uv run ruff check .                   # Lint (whole repo, as CI does — .claude/ included)
uv run ruff format .                  # Format (whole repo)
uv run pre-commit run --all-files     # Exactly what CI runs: ruff, ruff format, mypy, audit
uv run mypy                           # Static type check (src + tests + scripts)
uv run python -m open_coach.server  # Start MCP server (stdio)
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs ruff + mypy + pytest + `audit_docs.py`; the same hooks exist locally via `.pre-commit-config.yaml`.

## Architecture

The project is an **MCP server plus coaching guides** that exposes watch-platform tools (Garmin Connect today) to any MCP client. Claude Code is the reference client (it also loads the guides as skills and runs the hooks); every other client gets the same rules and workflows through the server itself.

### Execution flow

```
MCP client ──(.mcp.json / .cursor/mcp.json / .gemini/settings.json …)──► FastMCP server (server.py)
                                    │ instructions: instructions.py (operating rules, every client)
                                    │ lifespan: watch provider (Garmin) + Strava client + CoachStorage
                                    ├── tools/    (read + write; read tools mirror every key resource)
                                    ├── resources coach:// (read)
                                    └── prompts   (one per workflow guide)
```

`server.py` initializes the watch provider (`providers.create_provider()` — Garmin by default, OAuth2 token-cache-first via `providers/garmin_auth.py`), the optional Strava client (`strava_client.py` — `None` if no token cache), and `CoachStorage` in the lifespan. The three are shared via `ctx.lifespan_context["watch"]` (read it with `tools/_common.get_watch(ctx)`), `ctx.lifespan_context["strava"]`, and `ctx.lifespan_context["storage"]`.

### Watch providers

Tools never call a vendor SDK: they go through a `WatchProvider` (`providers/base.py`, a `Protocol`) and its neutral models (`RunActivity`, `ActivityDetail`, `DailyHeartRate`, `RecoverySignals`, `PersonalRecord`). `providers/garmin.py` (`GarminProvider`) is the only implementation today; it owns every garminconnect call and every Garmin payload shape (`summaryDTO`, `dailySleepDTO`, PR `typeId`s…). All Garmin code lives in `providers/garmin*.py`: the provider, `garmin_auth.py` (login, token cache) and `garmin_workout.py` (DSL → Garmin workout). `tests/test_vendor_isolation.py` fails if `garmin` or `garminconnect` shows up anywhere else, apart from a short, justified allowlist.

`OPEN_COACH_WATCH` selects the provider (default `garmin`, the only supported value so far). Each upload in the workout registry records its `provider`.

**Adding a provider (e.g. COROS)**:
1. Implement the `WatchProvider` methods in `providers/<name>.py`, including a DSL → vendor workout translator (the counterpart of `providers/garmin_workout.py`). Numeric fields are `int | float`: keep the vendor's own number types.
2. Register it in `providers.create_provider()` / `SUPPORTED_WATCHES`.
3. Add mapping tests with realistic payloads (like `tests/test_provider_garmin.py`) and make sure the scenarios of `tests/test_provider_contract.py` pass against it.
4. Tools are vendor-neutral (`list_watch_workouts`, `clean_watch_calendar`, `archive_active_plan(cleanup_watch=…)`…): a new provider needs no tool change. Tool outputs that carry raw vendor payloads (`get_activity_details`, `get_training_status`, `list_watch_workouts`) pass the provider's own shape through to the LLM.

### Client portability

Clients differ: some never read `AGENTS.md`/`CLAUDE.md`, many ignore MCP resources, several have no prompts, weaker models struggle with string-encoded JSON. The server therefore carries everything itself:

| Need | Mechanism |
|---|---|
| Operating rules (context first, methodology, watch sync, activity analysis, safety) | `SERVER_INSTRUCTIONS` in `instructions.py`, sent at MCP initialization |
| Methodology + workflows | `guides.py` loads `.claude/skills/*` (single source); `tools/guides.py` serves them as MCP prompts, `coach://guide/{name}` and the `get_coaching_guide` tool. The wheel bundles them as `open_coach/_guides` (hatch `force-include`) |
| Resource data for tool-only clients | `get_coaching_context`, `get_active_plan`, `get_archived_plan` tools mirror `coach://context`, `coach://plan/active`, `coach://plans/archive/*` (same payload builders) |
| Rules that apply after a call | `next_steps` in the results of `generate_training_plan`, `save_training_plan`, `update_workout_completion` (watch sync, journal, Drive sync when configured) |
| Structured inputs | `save_training_plan(plan_json: TrainingPlan | str)`, `upload_workout` / `build_and_push_workout(workout_json: DSLWorkout | str)`: the JSON schema is published, strings stay accepted |
| Small context windows | `compact=True` (default) on `get_activity_details`, `get_training_status`, `list_watch_workouts` — drops empty fields, rounds floats, vendor-neutral (`_common.compact_payload`) |

`tests/test_llm_portability.py` guards all of this (every workflow skill has a prompt, instructions carry the key rules, typed params publish their schema…). Per-client setup: `docs/mcp-clients.md`.

When adding a workflow skill: create `.claude/skills/<name>/SKILL.md`, then add the name to `WORKFLOWS` and `GuideName` in `guides.py`. In a skill, name the tool (`get_coaching_context`, `get_coaching_guide("…")`) rather than a bare `coach://` read.

### Tool/resource registration

The `tools/*.py` modules are imported in `server.py` to trigger `@mcp.tool()` and `@mcp.resource()` registration. Import order matters: `server.py` must be imported **before** the tools (already the case — they import `mcp` from `server`).

### FastMCP gotcha: Context parameter

**Both `@mcp.tool()` and `@mcp.resource()` must type-annotate the context parameter as `ctx: Context` (from `fastmcp`).** An untyped `ctx=None` is treated as a regular user parameter — FastMCP exposes it in the input schema and passes `None` at call time, so any access to `ctx.lifespan_context[...]` crashes with `'NoneType' object has no attribute 'lifespan_context'`. For resources the failure surfaces earlier as `ValueError: URI template must contain at least one parameter`.

Access shared state via the **short form `ctx.lifespan_context[...]`** (the codebase convention). The longer `ctx.request_context.lifespan_context[...]` works too — `Context.lifespan_context` is a property that falls back to `request_context.lifespan_context` — but pick one form and stay consistent.

Correct signature:

```python
from fastmcp import Context

@mcp.tool(annotations={"readOnlyHint": True})
async def my_tool(arg: int, ctx: Context | None = None) -> dict:
    assert ctx is not None
    watch = get_watch(ctx)  # from open_coach.tools._common
    ...
```

### Pure computation layer (no I/O)

| Module | Responsibility |
|--------|---------------|
| `vdot.py` | Daniels-Gilbert: `calculate_vdot`, `predict_time`, `training_paces` |
| `training_load.py` | hrTSS → `calculate_load_series(…, end_date=)` → CTL/ATL/TSB (EWMA 42d/7d). Always pass the assessed day as `end_date` (the tools use `tools/_common.training_load_as_of`): rest days since the last run must decay the fatigue |
| `zones.py` | `pace_zones_from_vdot`, `hr_zones_karvonen`, resting/max HR estimation |
| `workout_dsl.py` | Pydantic DSL models + `parse_dsl(name, text)` (vendor-neutral) |
| `plan_generator.py` | `generate_plan` → `TrainingPlan` (phases base/build/peak/taper, recovery weeks) |
| `plan_to_dsl.py` | `convert_planned_workout(workout, paces)` — parses a plan session description (`3×1 km @ T 4:16-4:20 r 2'`, `10 km dont 15 min @ M`, `10 km incl. 15 min @ M`) into a `DSLWorkout`; **refuses** (returns a reason) rather than guessing a structure. Used by `sync_upcoming_workouts` |
| `race_predictor.py` | Race predictions, pacing splits, multi-component readiness |
| `recovery_monitor.py` | Multi-signal recovery scoring + adaptive recommendations |
| `plan_renderer.py` | `render_plan_to_markdown(plan)` — pure formatter; `write_plan_markdown` is the I/O wrapper |
| `plan_metrics.py` | `recompute_week_actuals(week)` — refreshes `actual_volume_km` (completed workouts + `extra_activities`) and `completion_rate` (rest / strength excluded). Used by `update_workout_completion` |
| `i18n.py` | `t(key, lang)` / `day_abbreviation` — EN/FR table for text the code generates (plan markdown, session descriptions, plan name). Language comes from `AthleteProfile.language` via `tools/_common.profile_language`; the conversation language is left to the LLM |

### Persistence

`CoachStorage` (`storage.py`) reads/writes JSON files in `~/.open-coach/`. Each model has a `schema_version` field. Tests use `CoachStorage(base_dir=tmp_path)` for isolation.

### Watch workouts

Upload / schedule / unschedule / delete go through the provider (`GarminProvider` wraps garminconnect ≥ 0.3.0, which has native `delete_workout()` / `unschedule_workout()`). The local registry `~/.open-coach/workouts/registry.json` (`WorkoutRegistry`) tracks all uploads for idempotent `clean_watch_calendar`.

### Date injection in resources

`coach://context` and `coach://plan/active` (and their tool mirrors `get_coaching_context` / `get_active_plan`) automatically inject `today` (ISO), `day_of_week`, `current_week` (week number in active plan) and `days_remaining`.

`coach://context` also carries `training_load` (CTL/ATL/TSB) computed live from the watch as of today, with `as_of` and `source` (`watch`, or `profile_snapshot` with a staleness note when offline). The CTL/ATL/TSB stored in the profile date from the last bootstrap: they are left out of the context's `profile` block, and tools that judge current form (race predictions / readiness / pacing, plan generation, recovery) use `tools/_common.load_profile_live()`, a copy with today's load — the stored profile is never rewritten. Load windows default to 180 days (`LOAD_WINDOW_DAYS`); shorter windows understate CTL.

### Plan lifecycle

`save_plan` auto-archives any *differently named* active plan before overwriting (`completed` if its end_date is past, else `abandoned`). `auto_archive_expired(grace_days=3)` archives an expired plan; it runs automatically when `coach://context` is read. `rename_active_plan` (tool) renames and refreshes the markdown copy. `archive_active_plan` accepts `status="completed"|"abandoned"`, deletes the auto-generated markdown copy, and by default removes future coach-created watch workouts (`cleanup_watch=True`).

### Plan markdown copies

`generate_training_plan`, `save_training_plan` and `update_workout_completion` automatically write a markdown rendering of the active plan to `<repo-root>/plans/<slug>-<race-date>.md` via `plan_renderer.write_plan_markdown`. Override with env `OPEN_COACH_PLANS_MD_DIR`. Failure to write the markdown is logged but does NOT fail the tool — the JSON save in `~/.open-coach/` is the source of truth. `plans/` is gitignored.

### Drive sync (optional, out-of-band)

`scripts/drive_sync.sh` is an `rclone`-based wrapper that syncs `<repo>/plans/` bidirectionally with a Google Drive folder, and pulls Drive read-only into a local Obsidian vault. **Drive is the source of truth** in this topology; the project's `plans/` directory is bidirectional (`bisync`, last mtime wins, conflicts kept as `*.conflict-*`); Obsidian is a read-only mirror (`rclone sync` with `--backup-dir` for safety). The script is fully out-of-band of the MCP server — no Python deps, no token files in `~/.open-coach/`, no MCP coupling. Personal values come from per-machine env vars (`OPEN_COACH_DRIVE_FOLDER_ID`, `OPEN_COACH_REPO_PLANS_DIR`, `OPEN_COACH_OBSIDIAN_PLANS_DIR`, optional `OPEN_COACH_DRIVE_REMOTE`). Setup and operations: `docs/drive-sync.md`.

### Strava integration

Read-only mirror of Strava activity data — useful when Garmin SSO is locked out or when the user records on a non-Garmin device.

| Module | Responsibility |
|--------|---------------|
| `strava_auth.py` | OAuth2 token cache + auto-refresh (5 min leeway) at `~/.open-coach/strava_tokens.json` |
| `strava_client.py` | Thin urllib client, no extra deps. `fetch_activities` paginates `/athlete/activities` |
| `tools/strava.py` | `get_strava_activities(months, activity_type)` |
| `scripts/strava_setup.py` | One-shot OAuth |

**`after=` ordering gotcha**: Strava's `/athlete/activities?after=` returns **ascending** chronological order. `fetch_activities` reverses the list before returning so `result[0]` is the most-recent activity.

**Lifespan**: `strava_client` is `None` if the token cache is missing — the server still runs, the tool returns an `error` hint.

### Garmin SSO — operational caveat

`providers/garmin_auth.py` uses a **token-cache-first** strategy: if `~/.garth/garmin_tokens.json` exists, no SSO call is made. Garmin rate-limits SSO **per account**, with 48h+ lockouts on repeated failures. Never retry SSO in a tight loop. When the cache is missing or expired, recover via `scripts/garmin_re_auth.py` (SeleniumBase UC + DI exchange — Cloudflare-resistant).

### Environment variables

| Variable | Purpose | Required? |
|---|---|---|
| `GARMIN_EMAIL`, `GARMIN_PASSWORD` | First-time Garmin SSO login (cached afterwards) | yes (first run only) |
| `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` | Strava OAuth app credentials | optional |
| `OPEN_COACH_PLANS_MD_DIR` | Override destination for plan markdown copies | optional |
| `OPEN_COACH_MEMORY_DIR` | Override Claude memory dir scanned by `scripts/audit_docs.py` | optional |
| `OPEN_COACH_AUDIT_EXTRA_PATTERNS` | Extra leak-detection regexes (CSV) for `scripts/audit_docs.py` | optional |
| `OPEN_COACH_DRIVE_FOLDER_ID` | Google Drive folder ID for `scripts/drive_sync.sh` | optional (required only if using Drive sync) |
| `OPEN_COACH_REPO_PLANS_DIR` | Absolute path to `<repo>/plans/` for Drive sync | optional (required only if using Drive sync) |
| `OPEN_COACH_OBSIDIAN_PLANS_DIR` | Absolute path to local Obsidian plan dir for Drive sync | optional (required only if using Drive sync) |
| `OPEN_COACH_DRIVE_REMOTE` | rclone remote name (default `gdrive`) | optional |
| `OPEN_COACH_BISYNC_MAX_DELETE_PCT` | bisync mass-delete guard, percentage of files (default 50) | optional |
| `OPEN_COACH_OBSIDIAN_MAX_DELETE` | Obsidian pull mass-delete guard, file count (default 20) | optional |
| `OPEN_COACH_WATCH` | Watch provider (`garmin`, the default and only value so far) | optional |

On Windows, `setx` writes at User scope but is not visible in the current shell — open a new shell or load via PowerShell `[Environment]::GetEnvironmentVariable(name, 'User')`.

### Adding a new MCP tool or resource

1. Create the module under `src/open_coach/tools/` and decorate with `@mcp.tool()` or `@mcp.resource("coach://...")`.
2. **Annotate context as `ctx: Context` on every tool and resource** that needs lifespan state (see FastMCP gotcha). The codebase convention for tools is `ctx: Context | None = None` followed by `assert ctx is not None` (FastMCP always injects it at call time; the Optional default keeps direct test calls explicit). Resources use the required form `ctx: Context`.
3. Access shared state via `get_watch(ctx)` and `ctx.lifespan_context["strava" | "storage"]` — soft-fail if the watch provider or a client is `None` by returning `watch_error()` from `tools/_common.py` (never raise). Call `WatchProvider` methods only, never a vendor SDK (see "Watch providers"). `tools/_common.py` also holds the shared helpers: `resolve_target_date`, `avg_pace_sec_per_km`, `upload_and_register`, `schedule_and_record`, `save_active_plan` — reuse them instead of re-implementing.
4. Add the module to the import line in `server.py` so registration fires at startup.
5. If the module is pure-logic, put the algorithm in a sibling top-level module and keep `tools/*.py` as a thin I/O wrapper.

### Windows console encoding

Setup scripts and one-shot CLI helpers (`scripts/*.py`) run in cp1252 by default on Windows shells. Non-ASCII characters in `print()` crash with `UnicodeEncodeError`. Keep these scripts ASCII-only or set `PYTHONIOENCODING=utf-8` before invocation.

## Skills / guides architecture

Two layers of guides, written as Claude Code skills (loaded natively by Claude Code) and served to every other client over MCP (see "Client portability"):

- **`.claude/skills/entraineur/`** — coaching **methodology rules** (Daniels, 80/20, periodization, recovery, anti-patterns, DSL workout conventions). Sub-files in `references/` are loaded on demand (`get_coaching_guide("methodology" | "dsl-conventions" | "anti-patterns")`). **Does not pilot any MCP workflow.**
- **`.claude/skills/{onboard, plan-training, push-workout, analyze-run, daily-check, race-ready}/`** — **MCP workflows** (procedural guides that call MCP tools), also exposed as MCP prompts of the same name. Each references `entraineur` for the rules to apply.
- **`.claude/skills/extract-transcript/`** — repo maintenance skill (needs a shell), not served over MCP.

Triggers are designed to be non-overlapping: `entraineur` triggers on rule/methodology terms; the workflow skills trigger on action verbs.

## Personal data

All personal data (athlete profile, race calendar, constraints, preferences) lives in gitignored locations and is read at runtime with graceful fallback. **Never** hardcode personal values in versioned code. Full policy in `CONTRIBUTING.md`. Verify with `uv run python scripts/audit_docs.py` before any commit.
