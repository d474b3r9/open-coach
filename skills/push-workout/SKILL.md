---
name: push-workout
version: 1.0.0
description: Build a structured workout (DSLWorkout JSON) and push it to the Garmin calendar (calls build_and_push_workout, or upload_workout + schedule_watch_workout). Use when the user asks to schedule a specific session on a specific date.
---

# push-workout

MCP workflow to build a `DSLWorkout` and push it to the watch. **The strict rules for building the DSL** (lap_button warmup, easy run = 1 block, ±5 s pace target, warmup ≥ 15 min) live in the `entraineur` skill → `references/dsl-conventions.md` — load them before generating a workout.

## Steps

### 1. Read context

```
coach://context → VDOT + pace zones (coach://profile),
                  goals (coach://goals), constraints (coach://constraints)
```

### 2. Identify the session

From the athlete's request, infer:
- **Type**: easy / tempo / interval / long_run / recovery
- **Date**: when the session should be executed
- **Intensity**: derived from VDOT and session type (paces from `vdot.training_paces(vdot)`)

### 3. Build the DSLWorkout

Apply the conventions from `entraineur/references/dsl-conventions.md`:
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
