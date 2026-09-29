---
name: onboard
version: 1.0.0
description: Initialize the athlete profile by scanning Garmin history (VDOT, PRs, current load). Use only on first connection or when the user explicitly asks to (re)setup the profile.
---

# Onboard

MCP workflow to bootstrap the athlete profile. For the coaching rules to apply afterwards, see the `entraineur` skill.

## Steps

1. Read `coach://profile` → check if profile already exists
2. If absent → `bootstrap_athlete_profile` (scans 6 months of Garmin data)
3. Set the output language from the language the user writes in → `update_athlete_profile(language="en" | "fr")`. It drives the text the coach generates itself (plan markdown, session descriptions); the conversation always follows the user's language.
4. Present results: VDOT, personal records, training patterns, current CTL/ATL/TSB
5. Ask the user about training goals → `set_training_goal`
6. Ask about constraints (available days, time limits) → `set_training_constraints`
7. Summarize the complete profile

## Edge cases

- **Rate limit** on `bootstrap_athlete_profile` → suggest retry in 15 min, the scan is resumable.
- **Garmin SSO locked** → see `entraineur` § "Garmin SSO" before retrying anything.

## Output

Present a clear summary:
- VDOT and what it means for pace zones
- Key personal records detected
- Current training load status (fresh / tired / building)
- Recommended next steps based on declared goals
