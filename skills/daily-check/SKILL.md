---
name: daily-check
version: 1.0.0
description: Daily recovery check-in to decide if today's session proceeds, is modified, or skipped (calls get_recovery_status, get_adaptive_recommendation). Use when the user asks "should I train today", "comment je suis aujourd'hui".
---

# daily-check

MCP workflow for the daily recovery check-in + recommendation. For the overload thresholds and the downgrade logic, see the `entraineur` skill → `references/methodology.md` § "Post-race recovery" and § "Safeguards".

## Steps

### 1. Context
Read `coach://context` for profile, active plan, today's date.

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
- If the athlete accepts an adjustment → `record_workout_feedback`
- If session is skipped → `update_workout_completion(completed=False, skipped_reason=...)`

## Tone

Supportive and factual. Present data first, recommendation second. Don't ask "how do you feel?" if recent feedback exists (< 3 days). If all signals are green, encourage with confidence. If red, be direct: "Today is a rest day, your body needs it."
