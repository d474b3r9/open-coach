---
name: push-workout
description: Builds one structured workout (DSL) with VDOT-based pace targets and schedules it on the watch calendar. Use when the athlete asks to put a specific session on the watch for a given date — "push Tuesday's session to my watch", "envoie la séance sur ma montre".
compatibility: Requires the open-coach MCP server (watch data, training plans, coaching guides).
metadata:
  version: "1.0.0"
---

# push-workout

Workflow (tools of the open-coach MCP server) to build a `DSLWorkout` and push it to the watch. **The strict rules for building the DSL** (lap_button warmup, easy run = 1 block, ±5 s pace target, warmup ≥ 15 min) live in the `entraineur` methodology → `get_coaching_guide("dsl-conventions")` — load them before generating a workout. Session templates, pace tables and common mistakes: [references/conventions.md](references/conventions.md).

Copy this checklist and tick it off as you go:

```
Push progress:
- [ ] 1. Context read (get_coaching_context) and paces taken from get_training_zones
- [ ] 2. Session type, date and intensity identified
- [ ] 3. DSL built following dsl-conventions (lap_button warmup/cooldown, ±5 s pace window)
- [ ] 4. Checked: ≤ 50 steps, repeat ≤ 99, paces match VDOT, date free
- [ ] 5. Existing workout on that date checked with list_watch_workouts
- [ ] 6. Pushed (build_and_push_workout) and summary given to the athlete
```

## Steps

### 1. Read context

Call `get_coaching_context` (same data as the `coach://context` resource) → VDOT, goals,
constraints, active plan. Pace zones: `get_training_zones`.

### 2. Identify the session

From the athlete's request, infer:
- **Type**: easy / tempo / interval / long_run / recovery
- **Date**: when the session should be executed
- **Intensity**: derived from VDOT and session type (paces from `vdot.training_paces(vdot)`)

### 3. Build the DSLWorkout

Apply the conventions from `get_coaching_guide("dsl-conventions")`:
- Plain easy run → 1 step `repeat count=1` + `interval` distance-based + pace target. **No warmup/cooldown.**
- Quality session → `warmup` lap_button + body + `cooldown` lap_button, name carries volume + time targets.
- Pace target window = coaching target ± 5 sec/km (alert tolerance).

### 4. Validate before pushing

- Number of steps ≤ 50 (Garmin limit)
- Repeat count ≤ 99
- Paces consistent with VDOT
- Date available (no conflict with constraints)

### 5. Push

```
build_and_push_workout(workout_json=<json>, target_date=<YYYY-MM-DD>)
```

Or in two steps if the athlete wants to validate first:
```
1. upload_workout(workout_json=<json>) → returns workout_id
2. schedule_watch_workout(workout_id=<id>, target_date=<YYYY-MM-DD>)
```

`workout_json` also accepts the compact text DSL (then pass `name=` too):
```
WARMUP: 10min
REPEAT: 10
  INTERVAL: 1min @ 4:10-4:25/km
  RECOVERY: 1min
COOLDOWN: 10min
```

### 6. Confirm

Summarize the pushed session: name, date, structure, target paces, estimated duration.

### 7. Offer feedback

After execution: `record_workout_feedback(activity_id=<id>, workout_type=..., ...)`.

## Edge cases

- **429 Rate limit** → wait 15 min and retry.
- **Workout already exists** → use `list_watch_workouts` to check, `delete_watch_workout` if needed.
- **Past date** → Garmin accepts it but the watch won't sync.

## Cleanup

```
clean_watch_calendar(start_date=..., end_date=...)
```
