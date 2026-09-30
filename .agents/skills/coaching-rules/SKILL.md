---
name: coaching-rules
description: Coaching methodology rules for running — Daniels VDOT paces, 80/20 intensity, periodization, recovery, nutrition, anti-patterns and watch-workout (DSL) conventions. Use before any coaching decision (plan, session, pace, recovery advice) and when the user asks whether something follows the rules — "is this VDOT-correct?", "règle", "méthodo", "principe coaching", "est-ce conforme à la méthodo ?". Holds rules only; the workflow skills (onboard, plan-training, push-workout, analyze-run, daily-check, race-ready) perform the actions.
compatibility: Requires the open-coach MCP server (watch data, training plans, coaching guides).
metadata:
  version: "3.1.0"
---

# Skill `coaching-rules` — coaching rules (reference)

Always answer in the athlete's language (the language they write in; `profile.language` from `coach://context` sets the language of text the code generates).

A **methodology rules** skill. This skill does not drive an MCP workflow — it describes the methodology every coaching workflow must follow.

To perform a concrete action (generate a plan, push a workout, debrief a run, etc.), use the matching workflow skills: `plan-training`, `push-workout`, `analyze-run`, `daily-check`, `race-ready`, `onboard`. Each workflow references this skill for the applicable rules.

## Personalisation — bootstrap

Before reading any rule, check that the athlete profile exists:

1. **If `plans/athlete-profile.md` AND `plans/training-journal.md` both exist** → read both, then apply the rules below **with** the values found in the profile.
2. **If either is missing** → ask the user to run `uv run python scripts/setup_local.py` and then edit the profile with their values (VDOT, calendar, constraints…).
3. **If you have no file access** (desktop / web chat client using only the MCP server) → skip the markdown files and work from `get_coaching_context`; the stored profile, goals, constraints and recent feedback carry the essentials.

## Reading cycle for a coaching answer

1. **Read** `plans/athlete-profile.md` (profile) + `plans/training-journal.md` (history, last 30 entries take priority)
2. **Identify** in the profile: VDOT, physical constraints, race calendar, nutrition preferences, week structure, personal anti-patterns
3. **Spot** in the journal: recent tests (VDOT calibration), active insights (implicit constraints), recent decisions (consistency to maintain), missed sessions (caution signal)
4. **Apply** the rules below + the reference files listed next, cross-checked against the profile values
5. **Append** to the journal at the end of the task if a significant event occurs (see § "Journal update")

## Available rules (sub-files loaded on demand)

- [references/methodology.md](references/methodology.md) (MCP: `get_coaching_guide("methodology")`) — universal principles: Daniels VDOT, 80/20, CTL progression, recovery, plan structure, tests, safeguards
- [references/dsl-conventions.md](references/dsl-conventions.md) (MCP: `get_coaching_guide("dsl-conventions")`) — strict rules for generating a `DSLWorkout` pushed to the watch (lap_button, easy run = 1 block, ±5 s pace target, warmup ≥ 15 min, etc.) + French / English glossary
- [references/anti-patterns.md](references/anti-patterns.md) (MCP: `get_coaching_guide("anti-patterns")`) — patterns to NEVER do (starter gel, duplicate tests, Garmin SSO retry, hardcoded pace, etc.) + strength / tendon / ankle protocols + race nutrition

Load a sub-file only if the rule it covers is relevant to the question asked.

## Journal update (end of task)

Append to the journal **IF** one of these events occurs:

| Event | Journal section |
|---|---|
| Session run reported by the athlete | § Sessions run |
| Plan decision, adaptation, recalibration | § Coaching decisions |
| An athlete pattern emerges or is confirmed | § Athlete insights |
| A metric changes (test, measurement, VDOT recalibration) | § Metric changes |
| A race takes place | § Races + § Sessions run |

**Format**:
- ISO date `YYYY-MM-DD` in bold
- Visual tag: 🏁 race / 📊 measurement / ✅ validated decision / ❌ rejected approach / 💡 insight / ⚠️ alert
- 1-3 lines max per entry
- **Always state the why** (the reason matters more than the what in the long run)

**Append-only**: add at the bottom of each section, never rewrite past entries (history stays intact even when a decision is revised — append a new entry that supersedes the old one).

## Longitudinal adaptation (use the journal)

On every task, re-read the last 30 journal entries. Patterns to look for:

| Observed pattern | Adaptation to propose |
|---|---|
| 2-3 long runs > 2 h mentioning GI issues | Adjust the gel format before proposing (space them out or change format) |
| A "heavy" week mentioned twice in the month | Schedule the recovery week earlier than planned |
| 10K test confirms VDOT +1 | Recalibrate every pace in the plan (cascade profile + plans) |
| Several quality sessions missed over 2 weeks | Investigate the cause (sleep, load, work life) before proposing an adaptation |
| Repeated "doesn't like X" insights | Stop proposing X, even indirectly |

**Meta rule**: journal insights **override universal principles** when they conflict. If the journal says "the athlete blew two races by starting too fast", the "strict pacing" rule becomes inviolable for this athlete, less negotiable than for someone else.

## MCP workflow (reminder)

To perform a concrete action, use the appropriate workflow skill:
- **Onboarding** → `onboard`
- **Plan generation / update** → `plan-training`
- **Push a workout to the watch** → `push-workout`
- **Session debrief** → `analyze-run`
- **Daily check-in** → `daily-check`
- **Race preparation** → `race-ready`

Each workflow reads its MCP context (`get_coaching_context`, same data as the `coach://context` resource) and applies this skill's rules. Clients without skills get the same workflows as MCP prompts, or through the `get_coaching_guide` tool.

Behaviours encoded in the generator/predictor (do not re-derive by hand):
- The `max_weekday_minutes` / `max_weekend_minutes` constraints **cap the duration of generated sessions** (easy / long run: distance reduced; tempo: threshold block reduced, floor 2 km; intervals: reps reduced, floor 3).
- Active injuries and constraint `notes` are **surfaced in the response** of `generate_training_plan` (`warnings`, `constraints_notes`) — it is up to the coach to translate them into adaptations. Close a healed injury with `resolve_injury`.
- Half / marathon predictions apply an **endurance penalty if CTL < 50** (capped at +6 %) — a fresh VDOT on a thin aerobic base no longer promises an unrealistic marathon time.
- An archived plan can be re-read via `coach://plans/archive/{slug}` (or the `get_archived_plan` tool) to compare cycles.

## Garmin SSO — operational note

If SSO is locked (Cloudflare WAF, per-account rate limit 48 h+), do not retry SSO — every attempt extends the lockout window. Work from the local markdown files until it unlocks. Recovery via `scripts/garmin_re_auth.py` (SeleniumBase UC).
