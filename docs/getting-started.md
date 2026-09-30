# Getting started with Open Coach

A long-form walkthrough — what this project does, why it's built the way it is, how to get value out of it on day 1, and how to extend it.

If you just want to install and run, the [`README`](../README.md) covers that in 5 minutes. This document is for people who want to *understand* before they trust it with their training plan.

---

## 1. Why this project exists

### The problem

Most running apps fall in two camps:

- **Static plan generators** (Garmin Coach, Runna, generic free PDFs): pick a goal time, click a button, get a plan. Zero context awareness. They don't know you tweaked your knee last week, that one weekday evening is capped at forty minutes, or that you just DNF'd a marathon because you went out too fast. They reschedule nothing.
- **Connected coaching platforms** (TrainingPeaks, Final Surge, real human coaches over SMS): great context awareness, but expensive, slow feedback loops, and often opaque on *why* a session is what it is.

Personal-tooling project: bridge the gap. Take the **rigor of Daniels-Gilbert VDOT methodology** (objective, reproducible, well-validated), express the **coaching rules explicitly as a Claude skill** (transparent, auditable, debuggable), and let Claude orchestrate the **data plane** (Garmin Connect + Strava + local state) through MCP tools.

### Design constraints

Three constraints shaped the architecture:

1. **No vendor lock-in to a single device.** Strava as fallback when Garmin SSO is locked out, optional Google Drive sync to share plan markdown across machines, plain JSON for all local state.
2. **Methodology auditable, not hardcoded.** Coaching rules sit in `.agents/skills/entraineur/SKILL.md`. You can read them. You can argue with them. You can fork them. They are *not* buried in a planner function.
3. **Personal data never leaks into the repo.** Templates ship; values stay local. Any fork starts from a blank slate, not from someone else's race calendar.

---

## 2. Architecture deep dive

### The two-layer split: methodology vs. data

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   Claude Code  ←→  entraineur skill (methodology rules)     │
│        │                                                    │
│        │     (consults rules BEFORE any recommendation)     │
│        ↓                                                    │
│   MCP tools  ←→  FastMCP server (data plane)                │
│        │                                                    │
│        ├─→  Garmin Connect (OAuth2 token cache)             │
│        ├─→  Strava API (read-only fallback)                 │
│        ├─→  ~/.open-coach/*.json (local state)            │
│        └─→  Pure-computation modules (vdot, zones, plans)   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Two distinct layers because they answer different questions:

| Layer | Question it answers | Examples |
|---|---|---|
| **`entraineur` skill** | "Is this idea methodologically sound?" | "Is back-to-back hard days OK?" "Can I do hill repeats with this constraint?" "What's the right recovery format for VO2max work?" |
| **MCP server (data)** | "What does the data say?" | "What were my last 5 runs?" "What's my VDOT?" "When was my last hard session?" |

The skill is **read by Claude on the way in** (every coaching turn pre-loads the rules). The MCP tools are **called by Claude as needed**. The split keeps reasoning transparent: if Claude proposes something weird, you can audit it by reading the rule that backed (or didn't back) the decision.

### Workflow skills layer (above `entraineur`)

Workflow skills sit in `.agents/skills/` next to `entraineur`. They follow the [Agent Skills](https://agentskills.io) open standard: Codex, Gemini CLI, Cursor, Copilot and Claude Code (through the `.claude/skills` symlink) load them natively; every other MCP client gets them from the server as `skill://` resources, MCP prompts of the same name or the `get_coaching_guide` tool. Each one wraps a procedural use case:

| Skill | What it does | When it triggers |
|---|---|---|
| `onboard` | Bootstraps your profile, goals, constraints | "I'm new", "set me up", first-time use |
| `plan-training` | Generates a periodized plan for a target race | "build me a plan for X" |
| `push-workout` | Builds a structured workout via DSL, uploads to Garmin | "push tomorrow's session", "send the fartlek to my watch" |
| `analyze-run` | Inspects recent runs, reports anomalies | "how was Sunday's long run?", "did I hit the splits?" |
| `daily-check` | Multi-signal recovery + adaptive session | "should I train hard today?" |
| `race-ready` | Pre-race readiness, pacing, taper sanity | "am I ready for Sunday?" |

Each workflow skill *references* `entraineur` for the rules. It calls MCP tools to fetch data. The split prevents combinatorial explosion: 6 workflows × 1 rule set = 6 surface areas to maintain, not 6 × 30 rules duplicated.

### Pure-computation modules

The most testable code lives in pure modules (no I/O), under `src/open_coach/`:

| Module | Responsibility | Refs |
|---|---|---|
| `vdot.py` | Daniels-Gilbert VDOT engine. `calculate_vdot`, `predict_time`, `training_paces`. | Daniels, *Running Formula*, 4th ed. |
| `zones.py` | Pace zones from VDOT, HR zones via Karvonen. | Karvonen formula for HR; Daniels for paces. |
| `training_load.py` | hrTSS → `calculate_load_series` → CTL/ATL/TSB (EWMA 42d/7d). | Coggan, TSS/CTL methodology. |
| `workout_dsl.py` | Pydantic DSL models + `parse_dsl(name, text)`. | Custom. Designed for Garmin watch storage limits. |
| `providers/garmin_workout.py` | DSL → `RunningWorkout` (garminconnect schema). | Bridges DSL → Garmin API (Garmin provider). |
| `plan_generator.py` | `generate_plan` → `TrainingPlan` (Base/Build/Peak/Taper). | Periodization classic. |
| `race_predictor.py` | Race predictions from VDOT + pacing splits + readiness scoring. | Daniels + custom adjustments. |
| `recovery_monitor.py` | Multi-signal recovery scoring (HRV, sleep, stress, training load, subjective feel). | Adaptive recommendations. |
| `plan_renderer.py` | `render_plan_to_markdown(plan)` — pure formatter. | I/O wrapper in `write_plan_markdown`. |

These modules are covered by a comprehensive test suite. They don't touch Garmin, Strava, the filesystem, or the network. You can use them standalone if you just want a VDOT calculator.

### Why FastMCP

The Model Context Protocol (MCP) is the standard for exposing tools and resources to Claude. `fastmcp` is a Pythonic wrapper around the spec — handles transport, lifecycle, schema generation. Two affordances we use:

- **Lifespan context**: `server.py` initializes the Garmin client, Strava client, and storage *once* at startup. They live in `ctx.lifespan_context["garmin" | "strava" | "storage"]`. Any tool can access them without re-authenticating.
- **Resources** (`coach://...`): for read-only data Claude can pull *passively* (without it being a tool call). Examples: `coach://context` returns today's date, profile, active plan, and constraints. `coach://plan/active` returns the current week + days remaining.

### State persistence

`~/.open-coach/` holds the project's local state. Plain JSON, versioned with a `schema_version` field on each model:

```
~/.open-coach/
├── profile.json         athlete profile (VDOT, HRmax, resting HR, …)
├── goals.json           target races
├── constraints.json     injuries, agenda caps, preferences
├── plans/active.json    current training plan
├── feedback/<YYYY-Qn>.json   workout feedback, one file per quarter
├── workouts/registry.json   uploaded workouts (for idempotent cleanup)
└── strava_tokens.json   Strava OAuth tokens (auto-refresh)
```

No database. No migration framework. If you outgrow JSON you can write a one-shot upgrade script — but for personal-scale data (~thousands of activities over a career), JSON is fine and grep-friendly.

---

## 3. Walkthrough: your first session

This assumes you've already run `uv sync`, `scripts/setup_local.py`, and the Garmin/Strava setup steps from the README.

### Step 1 — Fill the templates

After `setup_local.py`, you have:

- `plans/athlete-profile.md` — your athlete profile (VDOT, HRmax, resting HR, race calendar, constraints, nutrition prefs)
- `plans/training-journal.md` — append-only journal (Claude will write to this; you can too)

The templates are in English by default; run `uv run python scripts/setup_local.py --lang fr` for the French versions. To get plan markdown and session descriptions in French too, ask Claude to set your language (`update_athlete_profile(language="fr")`).

Open `athlete-profile.md` and fill the placeholder sections. The template is annotated, so the format becomes clear quickly. Focus on:

- VDOT (compute from a recent race or use a reference time)
- HRmax (lab test, race max, or 220−age as fallback)
- Resting HR
- 1-2 target races with dates
- 1-3 physical constraints (e.g. "sensitive knee → no downhill repeats")
- Weekly schedule constraint (e.g. "Wednesday capped at 40 min")

### Step 2 — Open your MCP client in this repo

The walkthrough below uses Claude Code, the reference client. The `.mcp.json` file at the repo root makes Claude Code start the MCP server (approve the project server when prompted). Skills under `.agents/skills/` load because the repo is your open workspace.

Cursor (`.cursor/mcp.json`) and Gemini CLI (`.gemini/settings.json`) pick up the project configs shipped in the repo; Codex, VS Code, Claude Desktop and others need one snippet each — see [`mcp-clients.md`](mcp-clients.md). Those clients receive the same coaching rules through the server instructions, the workflows as MCP prompts, and the methodology through `get_coaching_guide`.

Open the project. Verify with a smoke ask:

> *"What's the current date?"*

The model should respond with today's date from `get_coaching_context` (or the `coach://context` resource). If it does not, the MCP server didn't load — check the logs (`uv run open-coach` directly to see startup errors).

### Step 3 — First real coaching turn

Try:

> *"Analyze my last 5 runs"*

What happens behind the scenes:

1. Claude loads the `analyze-run` workflow skill (matching trigger).
2. The skill instructs Claude to call `get_recent_runs(days=14, limit=5)`.
3. The MCP server reaches Garmin, returns 5 most recent runs with HR / pace / distance / cadence / etc.
4. Claude reads `entraineur` rules (loaded at startup) for the analytical lens (e.g. easy = E-pace, no hard days back-to-back, …).
5. Claude generates a human report.

You should get something like a per-session breakdown with "what was the goal", "what was the actual", "deviation analysis", "trend over the 5 sessions". If you have an active plan, Claude will also reference the expected session per the plan.

### Step 4 — Generate a plan

> *"Build me a 12-week plan for a half-marathon on October 15th"*

What happens:

1. `plan-training` workflow loads.
2. Claude reads your profile (VDOT, constraints).
3. Claude records the goal with `set_training_goal(race_name="Autumn half", distance_m=21097, race_date="2026-10-15")`, then calls `generate_training_plan(goal_index=0)`. The generator reads the goal and your VDOT from the stored profile.
4. The plan generator computes phases (Base/Build/Peak/Taper), respects constraints (no downhill repeats if a knee is flagged), and outputs a `TrainingPlan`.
5. Claude renders the plan as a Markdown file under `plans/<slug>-2026-10-15.md` (the `plan_renderer` module does this).
6. The plan also lands in `~/.open-coach/plans/active.json`.

You can review the markdown, edit it locally, or ask Claude to revise specific weeks.

### Step 5 — Push a session to your watch

> *"Push Tuesday's session to my watch"*

What happens:

1. `push-workout` workflow loads.
2. Claude reads tomorrow's planned session from `coach://plan/active`.
3. Claude assembles a DSL (`workout_dsl.parse_dsl`): WU + main set + CD with target paces.
4. The watch provider translates DSL (for Garmin, `providers/garmin_workout.build_running_workout`) to a `RunningWorkout` (the schema garminconnect expects).
5. `build_and_push_workout` MCP tool uploads + schedules it.
6. The workout appears on your Garmin watch by the next sync.

### Step 6 — Daily check

> *"Should I train hard today?"*

What happens:

1. `daily-check` workflow loads.
2. Claude calls `get_recovery_status()` → multi-signal score (HRV last night, sleep duration/quality, stress, training load TSB, subjective feel).
3. Reads today's planned session.
4. Applies `entraineur` rules: "if TSB < −15 and HRV deviation > 1σ → green-light Q2 only, defer Q1". "If sleep < 5h → swap quality for easy."
5. Outputs the adapted session — and updates the plan if you accept.

### Step 7 — Read what Claude wrote

After each coaching turn, Claude appends to `plans/training-journal.md`. Periodically open it — it's a longitudinal record of what was decided, why, and what happened. Better than scrolling chat history.

---

## 4. Extension guide

### Adding a new MCP tool

Follow `AGENTS.md` § "Adding a new MCP tool or resource". TL;DR:

```python
# src/open_coach/tools/your_module.py
from fastmcp import Context

from open_coach.server import mcp

@mcp.tool(annotations={"readOnlyHint": True})
async def your_tool(arg1: int = 0, ctx: Context | None = None) -> dict:
    """One-line summary visible to Claude."""
    assert ctx is not None  # FastMCP always injects it at call time
    garmin = ctx.lifespan_context["garmin"]
    storage = ctx.lifespan_context["storage"]
    # …
    return {"result": ...}
```

Then add `from open_coach.tools import your_module` to `server.py` so `@mcp.tool()` registration fires at startup.

**Both tools and resources must type-annotate the context parameter** (`ctx: Context | None = None` for tools, `ctx: Context` for resources). An untyped `ctx=None` is exposed to Claude as a user parameter, passed as `None`, and every access to `ctx.lifespan_context` crashes. **Resources** (URI-addressable read-only data) use `@mcp.resource("coach://...")`.

For pure-computation logic, put the algorithm in a sibling top-level module (`src/open_coach/<algo>.py`), then keep `tools/<algo>.py` as a thin I/O wrapper. The pure module is testable without the MCP server.

### Adding a coaching rule to `entraineur`

`.agents/skills/entraineur/SKILL.md` is the rule book. Sections are numbered (`## 1. …`, `## 2. …`, …). Add yours at the end, increment the count. If the rule comes from a specific incident, say so in the rule text with the date; the journal (`plans/training-journal.md`, private) is where the incident itself is recorded.

If your rule depends on athlete-specific data (e.g. "if HR cap is < 140 …"), make sure the rule reads it from `athlete-profile.md` at runtime — never hardcode.

### Adding a new workflow skill

```
.agents/skills/
└── your-workflow/
    └── SKILL.md      with YAML frontmatter (name, description)
```

Then add the name to `WORKFLOWS` and `GuideName` in `src/open_coach/guides.py` so the workflow is also served as an MCP prompt and through `get_coaching_guide` (`tests/test_llm_portability.py` checks it).

The `description:` field is what Claude uses to decide whether to trigger this skill. Make it specific so it doesn't collide with `entraineur` (which triggers on rule/methodology terms) or other workflows.

The body of `SKILL.md` is instruction in natural language. It typically:
1. Tells Claude what data to fetch (which MCP tools)
2. References `entraineur` for the rules to apply
3. Lays out the report format

### Adding pure-computation modules

Drop them as `src/open_coach/<module>.py`, no MCP imports. Write tests in `tests/test_<module>.py`. They become reusable by any tool that wants them.

---

## 5. FAQ

**Q: Why not just use TrainingPeaks / Final Surge?**

A: Those platforms have great UIs but the methodology is opaque (you can't read the planning logic, can't argue with it, can't modify it). They also charge $20-50/month. This project is for people who want full control + don't mind tinkering.

**Q: Why Claude specifically?**

A: It is not tied to Claude. Claude Code is the reference client (native skills + hooks), but the MCP server carries the methodology layer itself: operating rules in the server instructions, workflows as MCP prompts, methodology through `get_coaching_guide`, and tool mirrors for every resource. Cursor, Codex, Gemini CLI, VS Code, Claude Desktop or a local model behind an MCP front end all work — see [`mcp-clients.md`](mcp-clients.md). Pick a model with reliable tool calling.

**Q: Why not a web UI?**

A: A web UI adds enormous surface area (auth, hosting, frontend code, mobile responsive, …) for a personal-tooling project. The Claude Code terminal is the UI. The plan markdown files are the artifacts. The Garmin watch is the second screen.

**Q: Can I use this without a Garmin watch?**

A: Partial yes. Strava integration is read-only fallback — you can analyze runs recorded on any device that uploads to Strava. The plan-generation and DSL workout-building work without a watch. You just can't push workouts to a non-Garmin device.

**Q: What about Apple Watch / Polar / Coros / Suunto?**

A: Not supported. If your device exports to Strava, you can analyze your runs. If you want first-class integration with another platform, you'd write a parallel `<vendor>_auth.py` + `<vendor>_client.py` + `tools/<vendor>.py` set. The architecture allows it — nobody has done the work.

**Q: How is data privacy handled?**

A: Everything local. See `README` § "Privacy & data". No telemetry, no third-party servers, no `chmod 777` on tokens.

**Q: Does the coach speak English or French?**

A: Both. Claude replies in the language you write in. Generated text (plan markdown, session descriptions) follows the `language` field of your profile (`"en"` by default, `"fr"` available), and the plan-description parser understands both (`incl.` / `dont`). The repo itself is in English; the methodology skill keeps its original name, `entraineur` ("coach" in French).

**Q: How much Claude API / token cost does this generate?**

A: Depends entirely on usage. Casual daily check-in: minimal. Generating a 16-week plan from scratch: a few thousand tokens. The MCP tool calls themselves are cheap — most cost comes from Claude reasoning over the returned data.

**Q: Can I run the MCP server somewhere else and call it remotely?**

A: Yes, in theory — FastMCP supports HTTP transport. In practice this is a personal-tool project running locally; remote deploy would need auth/TLS/etc., not currently scaffolded.

---

## 6. Troubleshooting

### Garmin SSO: HTTP 429 / "too many requests" / lockout

**Symptom.** Starting the MCP server (or running any Garmin tool) raises a `429` from `sso.garmin.com` or `diauth.garmin.com`, or `garminconnect` reports the login chain exhausted.

**Why it happens.** Garmin's SSO sits behind Cloudflare and rate-limits **per account** (not per IP). Each failed login extends the lockout window — repeated retries make it worse, up to 48h+. Common triggers:

- Missing or corrupted `~/.garth/garmin_tokens.json` → `providers/garmin_auth.py` falls back to a fresh SSO call on every server start.
- Wrong credentials or MFA enabled → every attempt counts against the lockout.
- VPN / corporate proxy / aggressive firewall → Cloudflare flags the traffic.
- Tight retry loop in a script or shell.

**Fix — do this in order:**

1. **Stop all login attempts.** Every retry pushes the lockout further. Wait 24–48 h before the next step.
2. Check the token cache: `ls ~/.garth/garmin_tokens.json`. If it exists and is recent, the 429 is not coming from SSO — it's API-side; report which MCP tool triggers it.
3. Disable VPN/proxy. Use a residential IP.
4. **Temporarily disable MFA** on the Garmin account (Account Security → 2-step verification). The recovery script raises on `MFA_REQUIRED`.
5. Install the recovery extra (SeleniumBase + curl_cffi are not part of the default install) and run the script **once**:
   ```bash
   uv sync --extra reauth
   uv run python scripts/garmin_re_auth.py --email "$GARMIN_EMAIL" --password "$GARMIN_PASSWORD"
   ```
   It opens a real Chrome via SeleniumBase UC (bypasses Cloudflare), POSTs the SSO login from inside the page, then exchanges the service ticket against `diauth.garmin.com` with a Chrome TLS fingerprint (`curl_cffi`). On success it writes `~/.garth/garmin_tokens.json` in the format `garminconnect 0.3.x` expects.
6. Re-enable MFA.
7. Verify:
   ```bash
   uv run python scripts/smoke_mcp.py
   ```

After this, `providers/garmin_auth.py` resumes from the token cache on every start and makes **zero** SSO calls — the 429 should not come back unless the cache is deleted or expires.

**If the 429 happens inside the recovery script itself** (on `diauth.garmin.com`, step 2/2): Cloudflare is rate-limiting that endpoint too. The script raises explicitly. **Wait 1 h+, do not retry tightly.**

**Caveats:**

- The recovery script requires `seleniumbase` and `curl_cffi`, installed only by `uv sync --extra reauth`, and a local Chrome or Chromium that SeleniumBase can drive.
- MFA must be off for the duration of the recovery — the script does not handle the TOTP challenge.
- Never seed `~/.garth/` from a `garth`-only login (`oauth1_token.json` / `oauth2_token.json`): those are a different format and `garminconnect 0.3.x` will not read them. The recovery script auto-deletes them to avoid confusion.

### Other common issues

- **`ValueError: URI template must contain at least one parameter`** at server startup → an `@mcp.resource()` function has an untyped `ctx=None` parameter. Annotate it as `ctx: Context` (see `AGENTS.md` § FastMCP gotcha).
- **Strava tool returns `{"error": ...}`** → `~/.open-coach/strava_tokens.json` is missing. Run `scripts/strava_setup.py` once.
- **Claude Code lists no coaching skills (Windows)** → `.claude/skills` was checked out as a text file instead of a symlink to `.agents/skills`. Enable Developer Mode, run `git config --global core.symlinks true`, then `git checkout -- .claude/skills` (or re-clone). See [`mcp-clients.md`](mcp-clients.md#skills-standards-followed-and-known-limits).
- **A model ignores the methodology** → loading a guide is left to the model. Start with the workflow prompt (`/plan-training`…) or ask it to call `get_coaching_guide`; prefer a model with reliable tool calling.
- **`UnicodeEncodeError` in a setup script on Windows** → cp1252 console. Set `PYTHONIOENCODING=utf-8` before running, or keep the script ASCII-only.

---

## 7. Next steps

- Read [`AGENTS.md`](../AGENTS.md) for contributor-level architecture details, and [`mcp-clients.md`](mcp-clients.md) to use another MCP client.
- Read [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the data separation policy.
- Browse [`.agents/skills/entraineur/SKILL.md`](../.agents/skills/entraineur/SKILL.md) to see the methodology rules.
- Browse [`.agents/skills/`](../.agents/skills/) to see each workflow's instructions.
- Run `uv run pytest --co -q` to enumerate tests and spot-check coverage.

Bonne course.
