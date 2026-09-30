---
name: coaching-rules-running
description: Running coaching rules — Daniels VDOT paces, running plan structure and tests, post-race recovery, watch-workout (DSL) conventions for runs, running anti-patterns, strength and tendon protocols, race nutrition. Use together with coaching-rules before any running decision (plan, session, pace, recovery advice) and when the user asks whether a running session follows the rules — "is this VDOT-correct?", "allure VDOT", "séance conforme ?", "règle course à pied". Holds rules only; the workflow skills perform the actions.
compatibility: Requires the open-coach MCP server (watch data, training plans, coaching guides).
metadata:
  version: "1.0.0"
---

# Skill `coaching-rules-running` — running rules (reference)

Running layer of the coaching rules. Read `coaching-rules` first (universal rules, athlete profile, journal); this guide adds what is specific to running. Every pace derives from the running VDOT (`profile.sports.running.fitness`, or `get_training_zones(sport="running")`) — never from memory.

## Available rules (sub-files loaded on demand)

- [references/methodology.md](references/methodology.md) (MCP: `get_coaching_guide("running-methodology")`) — Daniels VDOT, plan structure, tests and milestones, 10K test inside a marathon block, post-race recovery, safeguards
- [references/dsl-conventions.md](references/dsl-conventions.md) (MCP: `get_coaching_guide("running-dsl-conventions")`) — strict rules for generating a running `DSLWorkout` pushed to the watch (lap_button, easy run = 1 block, ±5 s pace target, warmup ≥ 15 min, etc.) + French / English glossary
- [references/anti-patterns.md](references/anti-patterns.md) (MCP: `get_coaching_guide("running-anti-patterns")`) — patterns to NEVER do (starter gel, duplicate tests, Garmin SSO retry, hardcoded pace, etc.) + strength / tendon / ankle protocols + race nutrition

Load a sub-file only if the rule it covers is relevant to the question asked.

## Behaviours encoded in the running plugin (do not re-derive by hand)

- The `max_weekday_minutes` / `max_weekend_minutes` constraints **cap the duration of generated sessions** (easy / long run: distance reduced; tempo: threshold block reduced, floor 2 km; intervals: reps reduced, floor 3).
- Half / marathon predictions apply an **endurance penalty if CTL < 50** (capped at +6 %) — a fresh VDOT on a thin aerobic base no longer promises an unrealistic marathon time.
- `sync_upcoming_workouts` pushes only sessions that carry quality (tempo, intervals, race, long runs with an embedded pace block); easy runs are run on feel.
