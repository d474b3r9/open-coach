---
name: analyze-run
description: Debriefs a completed run against the plan and the training zones (pace, heart rate, splits, cardiac drift, training effect). Use when the athlete asks to review a workout or a race — "how was my run", "analyse ma sortie", "débriefe ma séance".
compatibility: Requires the open-coach MCP server (watch data, training plans, coaching guides).
metadata:
  version: "1.0.0"
---

# analyze-run

Workflow (tools of the open-coach MCP server) to analyse a completed run. For the interpretation rules (zones, drift, VDOT recalibration), see the `entraineur` methodology → `get_coaching_guide("methodology")`.

## Steps

1. Call `get_coaching_context` (same data as the `coach://context` resource) for the athlete's profile, goals, current fitness
2. `get_recent_runs` → find the relevant activity
3. `get_activity_details` → full metrics (splits, HR, pace)
4. Compare with training zones from the profile:
   - Was the pace in the correct zone for the workout type?
   - How was HR relative to effort (cardiac drift)?
   - Pace consistency across splits (even / negative / positive split)
5. Provide actionable analysis
6. Ask for subjective feedback → `record_workout_feedback`

## Analysis points

- **Pace**: consistency, splits, comparison to zone targets
- **HR**: drift over time, avg HR vs expected for effort level
- **Training effect**: estimated TSS, impact on CTL/ATL/TSB
- **Recovery**: based on effort level and recent training load

## Tone

Be encouraging but honest. Highlight what went well first, then areas to improve. Frame recommendations in terms of the athlete's stated goals.
