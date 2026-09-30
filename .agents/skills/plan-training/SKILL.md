---
name: plan-training
description: Generates or updates a periodized training plan for a target race (base, build, peak, taper) and syncs its quality sessions to the watch. Use when the athlete asks for a plan, prepares a race, or reports an event that changes the plan (injury, holiday, missed week) — "build me a marathon plan", "prépare-moi un plan", "adapte mon plan".
compatibility: Requires the open-coach MCP server (watch data, training plans, coaching guides).
metadata:
  version: "1.0.0"
---

# plan-training

Workflow (tools of the open-coach MCP server) to generate / update a training plan and sync it with the watch. For the coaching rules (Daniels, 80/20, phase structure, test placement), see the `coaching-rules` methodology (`get_coaching_guide("methodology")`). For the DSL conventions of pushed workouts, see `get_coaching_guide("dsl-conventions")`.

Copy this checklist and tick it off as you go:

```
Plan progress:
- [ ] 1. Context read (get_coaching_context): profile, goals, constraints, today
- [ ] 2. Missing data asked (days, time caps, injuries)
- [ ] 3. Plan generated (generate_training_plan)
- [ ] 4. Plan presented and confirmed by the athlete
- [ ] 5. Quality sessions synced to the watch; easy runs reported as left unpushed
- [ ] 6. next_steps from the tool results carried out (journal, sync)
```

## Steps

### 1. Read context (mandatory)

Call `get_coaching_context` (same data as the `coach://context` resource) → profile (VDOT, CTL, weekly pattern) + goals + constraints + today's date.

Verify:
- `profile.onboarding_complete: true` → otherwise suggest the `onboard` skill first
- At least one goal with `race_date` → otherwise call `set_training_goal`
- Constraints available → if missing, ask the athlete for available days

### 2. Clarify if needed

Ask only if the data is missing from the profile:
- "Which days do you train?" → `set_training_constraints(available_days=[...])`
- "Maximum time on weekdays? On weekends?"
- "Any recent injuries I should account for?"

### 3. Generate

```
generate_training_plan(start_date?, goal_index?)
```

- `start_date`: defaults to next Monday
- `goal_index`: 0 = first goal (priority A)

### 4. Present

- Total duration (weeks) and phases (base / build / peak / taper)
- Starting volume and peak volume
- Typical week structure
- First 2 weeks in detail (no need to dump every session of every week)

Ask for confirmation: "Does this plan work for you?"

### 5. Sync to the watch (if connected and confirmed)

```
sync_upcoming_workouts(weeks_ahead=2)
```

Only quality sessions are pushed; easy runs come back in `left_unpushed` (report them as intentionally left off the watch). Sessions in `not_converted` (e.g. a `race`) are pushed by hand with `build_and_push_workout` if needed.

If `rate_limited`: wait ~2 minutes and retry.

## Ongoing tracking

After each completed session:
```
update_workout_completion(week_number, workout_date, completed=True, activity_id?, actual_distance_m?, actual_duration_s?)
```

If skipped:
```
update_workout_completion(week_number, workout_date, completed=False, skipped_reason="...")
```

Sync the next week every Sunday or Monday:
```
sync_upcoming_workouts(weeks_ahead=1)
```

## Unexpected events

If the athlete reports an unexpected event (vacation, injury, conflict):
1. Identify impacted weeks
2. Propose based on duration:
   - < 1 week: mark sessions as skipped, don't modify the plan
   - 1-2 weeks: regenerate from the restart date with `generate_training_plan(start_date=...)`
   - Injury: `report_injury(description, body_part, severity)` + reduce load
3. Regenerate if needed with the new start date
