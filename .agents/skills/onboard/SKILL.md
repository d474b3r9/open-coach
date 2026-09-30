---
name: onboard
description: Initializes the athlete profile from the watch history (VDOT, personal records, training pattern, current load), then records goals, constraints and output language. Use on first connection or when the athlete explicitly asks to set up or reset the profile — "onboarding", "set up my profile", "configure mon profil".
compatibility: Requires the open-coach MCP server (watch data, training plans, coaching guides).
metadata:
  version: "1.0.0"
---

# Onboard

Workflow (tools of the open-coach MCP server) to bootstrap the athlete profile. For the coaching rules to apply afterwards, see the `coaching-rules` methodology (`get_coaching_guide("rules")`).

## Steps

1. Call `get_coaching_context` (`profile` block) → check if profile already exists
2. If absent → `bootstrap_athlete_profile` (scans 6 months of Garmin data)
3. Set the output language from the language the user writes in → `update_athlete_profile(language="en" | "fr")`. It drives the text the coach generates itself (plan markdown, session descriptions); the conversation always follows the user's language.
4. Present results: VDOT, personal records, training patterns, current CTL/ATL/TSB
5. Ask the user about training goals → `set_training_goal`
6. Ask about constraints (available days, time limits — per day too, e.g. "45 min on Mondays" → `max_minutes_by_day={"monday": 45}`) → `set_training_constraints`
7. Summarize the complete profile

## Edge cases

- **Rate limit** on `bootstrap_athlete_profile` → suggest retry in 15 min, the scan is resumable.
- **Garmin SSO locked** → see `get_coaching_guide("rules")` § "Garmin SSO" before retrying anything.

## Output

Present a clear summary:
- VDOT and what it means for pace zones
- Key personal records detected
- Current training load status (fresh / tired / building)
- Recommended next steps based on declared goals
