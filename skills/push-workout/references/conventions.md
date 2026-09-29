# Workout construction conventions

Reference for the push-workout skill. These rules prevent hallucinations
and ensure sessions are consistent with the Daniels-Gilbert method.

## Pace rules

| Bound | Formula | Example (VDOT 45, target 4:13/km) |
|-------|---------|----------------------------------|
| Low pace (fast) | target − 5 s/km | 4:08/km → 248 s/km |
| High pace (slow) | target + 10 s/km | 4:23/km → 263 s/km |

**Always** express in seconds per km in the JSON:
```
4:13/km = 4×60 + 13 = 253 s/km
```

## Daniels zones by VDOT (target paces)

| Zone | Name | % VDOT | Usage |
|------|------|--------|-------|
| E (Easy) | Easy endurance | 59-74% | 80% of volume, long runs |
| M (Marathon) | Marathon pace | 75-84% | Specific long runs |
| T (Threshold) | Lactate threshold | 83-88% | Tempo, 10-20min repeats |
| I (Interval) | VO2max | 95-100% | 3-5min intervals |
| R (Repetition) | Speed | 105-120% | Short repeats ≤2min |

Exact paces are computed by `calculate_vdot_from_race` and `get_training_zones`.
**Always** use zones from the profile (`coach://profile`) rather than hardcoded values.

## Recovery intervals

| Session type | Recovery duration | Recovery pace |
|-------------|-------------------|---------------|
| Intervals I | = interval duration | no_target |
| Repetitions R | 2-3× rep duration | no_target |
| Tempo (continuous) | no recovery | — |

## Template session structures

### Easy Run

```json
{
  "name": "Easy 8km",
  "steps": [
    {"type": "warmup",   "duration": {"distance_m": 1000}},
    {"type": "interval", "duration": {"distance_m": 6000},
     "pace": {"min_sec_per_km": 315, "max_sec_per_km": 355}},
    {"type": "cooldown", "duration": {"distance_m": 1000}}
  ]
}
```

### Tempo (continuous threshold)

```json
{
  "name": "Tempo 6km",
  "steps": [
    {"type": "warmup",   "duration": {"seconds": 600}},
    {"type": "interval", "duration": {"distance_m": 6000},
     "pace": {"min_sec_per_km": 248, "max_sec_per_km": 263}},
    {"type": "cooldown", "duration": {"seconds": 600}}
  ]
}
```

### VO2max Intervals

```json
{
  "name": "8x1000m I",
  "steps": [
    {"type": "warmup",  "duration": {"seconds": 900}},
    {"type": "repeat",  "count": 8, "steps": [
      {"type": "interval", "duration": {"distance_m": 1000},
       "pace": {"min_sec_per_km": 228, "max_sec_per_km": 240}},
      {"type": "recovery", "duration": {"distance_m": 400}}
    ]},
    {"type": "cooldown", "duration": {"seconds": 600}}
  ]
}
```

### Repetitions (speed)

```json
{
  "name": "10x200m R",
  "steps": [
    {"type": "warmup",  "duration": {"seconds": 900}},
    {"type": "repeat",  "count": 10, "steps": [
      {"type": "interval", "duration": {"distance_m": 200},
       "pace": {"min_sec_per_km": 198, "max_sec_per_km": 210}},
      {"type": "recovery", "duration": {"seconds": 90}}
    ]},
    {"type": "cooldown", "duration": {"seconds": 600}}
  ]
}
```

### Long Run

```json
{
  "name": "Long Run 20km",
  "steps": [
    {"type": "warmup",   "duration": {"lap_button": true}},
    {"type": "interval", "duration": {"distance_m": 18000},
     "pace": {"min_sec_per_km": 330, "max_sec_per_km": 360}},
    {"type": "cooldown", "duration": {"lap_button": true}}
  ]
}
```

## Garmin limits

| Parameter | Limit | Action if exceeded |
|-----------|-------|--------------------|
| Total steps | 50 max | Reduce repetitions |
| Repeat count | 99 max | Never an issue in practice |
| Name length | 120 chars | Keep it short |

## Common mistakes to avoid

1. **Low pace > high pace**: `min_sec_per_km` must be < `max_sec_per_km`
   - Correct: `{"min_sec_per_km": 248, "max_sec_per_km": 263}` (248 < 263 ✓)
   - Wrong: `{"min_sec_per_km": 263, "max_sec_per_km": 248}` ✗

2. **Forgetting recovery** in a REPEAT block for long intervals (>3min).

3. **Hardcoding paces** without checking the athlete profile. Always start from
   `get_training_zones(vdot=<vdot_from_profile>)`.

4. **Exceeding 50 steps**: 10×1000m with recovery = 1 (warmup) + 1 (repeat group) + 10×2 (inner steps) + 1 (cooldown) = 23 steps ✓

5. **Wrong date format**: use YYYY-MM-DD only.
