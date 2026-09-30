---
name: daily-check
description: Runs the daily recovery check-in (HRV, sleep, stress, training load, recent feedback) and decides whether today's session proceeds, is adjusted or becomes a rest day. Use when the athlete asks whether to train today — "should I train today", "how am I today", "comment je suis aujourd'hui", "je m'entraîne aujourd'hui ?".
compatibility: Requires the open-coach MCP server (watch data, training plans, coaching guides).
metadata:
  version: "1.0.0"
---

# daily-check

Workflow (tools of the open-coach MCP server) for the daily recovery check-in + recommendation. For the overload thresholds and the downgrade logic, see the running methodology → `get_coaching_guide("running-methodology")` (universal rules: `get_coaching_guide("principles")`) § "Post-race recovery" and § "Safeguards".

## Steps

### 1. Context
Call `get_coaching_context` (same data as the `coach://context` resource) for profile, active plan, today's date.

### 2. Recovery status
`get_recovery_status()`
- Overall score (0-100) and status (green / yellow / red)
- Detail of 5 signals: HRV, Sleep, TSB, Subjective, Stress

### 3. Adaptive recommendation
`get_adaptive_recommendation()`
- Concrete action: proceed / reduce_intensity / reduce_volume / swap_to_easy / rest_day
- Planned session vs adjusted session (with concrete paces)

### 4. Presentation

```
## Recovery — [SCORE]/100

| Signal | Score | Status | Detail |
|--------|-------|--------|--------|
| HRV    | ...   | green  | ...    |
| Sleep  | ...   | yellow | ...    |
| ...    |       |        |        |

## Today's Session
**Planned**: [session description]
**Recommendation**: [action]
[Adjustment detail if applicable]

## Tips
- [Recommendations from the analysis]
```

### 5. Follow-up
- If the athlete accepts an adjustment → apply it to the plan with `adjust_planned_workout(workout_date, workout_type?, description?, target_distance_m?, target_duration_s?, target_intensity?, reason=...)` (rest day: `workout_type="rest"`), then carry out its `next_steps` (unschedule the old watch workout for that date, push the new one only if it carries quality).
- If session is skipped → `update_workout_completion(completed=False, skipped_reason=...)`
- After the session → `record_workout_feedback`; it returns `active_injuries` when some are open — check in on each one.

## Tone

Supportive and factual. Present data first, recommendation second. Don't ask "how do you feel?" if recent feedback exists (< 3 days). If all signals are green, encourage with confidence. If red, be direct: "Today is a rest day, your body needs it."
