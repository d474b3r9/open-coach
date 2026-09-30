---
name: race-ready
description: Produces a race briefing — readiness score, time prediction and a split-by-split pacing strategy. Use when the athlete asks whether they are ready, for a race-day plan or a target pace — "am I ready for my race", "pacing plan", "stratégie de course", "allure cible".
compatibility: Requires the open-coach MCP server (watch data, training plans, coaching guides).
metadata:
  version: "1.0.0"
---

# race-ready

Workflow (tools of the open-coach MCP server) to produce a race briefing (readiness, prediction, pacing). For the interpretation rules (TSB, CTL, completion %, taper), see the `coaching-rules` methodology → `get_coaching_guide("methodology")`.

## Steps

### 1. Context
Call `get_coaching_context` (same data as the `coach://context` resource) for the full profile, goals, today's date.

### 2. Readiness
`get_race_readiness(goal_index=0)`
- Overall score and status (ready / caution / not_ready)
- Detail each component (VDOT, CTL, TSB, completion, long run)
- Highlight the weakest component with specific advice

### 3. Predictions
`get_race_predictions(goal_index=0)`
- Predicted time for the target distance
- Confidence interval (best / worst)
- Comparison to target time if set

### 4. Pacing
`get_pacing_strategy(goal_index=0)`
- Split table with pace and cumulative time
- Coaching cues for each segment
- Key guidance (nutrition, warmup, mental)

### 5. Recommendations
- List recommendations from the readiness assessment
- Race > 2 weeks → training adjustments
- Race < 2 weeks → taper and preparation focus
- Race < 3 days → logistics and mental prep only

## Presentation

```
## Readiness — [STATUS]
Overall score, components, weak point

## Predictions
Predicted time, confidence interval, comparison to target

## Pacing Plan
Split table, coaching cues

## Recommendations
Concrete actions
```

## Tone

Confident but honest. If not ready, say so clearly but constructively — offer realistic alternative targets. If ready, build confidence with data-backed encouragement. Adapt the discourse to the distance (5K ≠ marathon in terms of preparation).
