# DSL workout conventions (watch push)

## Contents

- Rule A — Easy run = ONE block, no warmup/cooldown
- Rule B — Warmups/Cooldowns = `lap_button` by default
- Rule B-bis — Volume + time target IN THE NAME (corollary of B)
- Rule B-ter — Warmup MINIMUM 15 min on a quality session
- Rule B-quater — Pace target = coaching target ±5 s (watch alerts)
- Rule D — End of session = ALWAYS a lap press (never an automatic end)
- Rule E — `sync_upcoming_workouts` never guesses a structure
- Rule C — Classification before build
- Example: easy run + strides
- French / English equivalents

Reference loaded by the `coaching-rules` skill when a `DSLWorkout` must be generated to push to the watch. Strict rules — empirically validated preferences (can be overridden in the athlete profile § "Preferences" if the athlete gives different feedback).

This applies to every flow that pushes to Garmin: `build_and_push_workout`, `sync_upcoming_workouts`, ad-hoc scripts, `generate_training_plan`.

## Rule A — Easy run = ONE block, no warmup/cooldown

A plain easy run (easy, recovery, basic endurance) must be **a single `repeat count=1` containing a distance-based `interval`** with a pace target. No warmup, no timed cooldown — **only** the final `lap_button` step required by Rule D (added automatically by the builder).

```json
{"sport": "running", "name": "Easy run 7 km <pace> HR<<bpm>>", "steps": [
  {"type": "repeat", "count": 1, "steps": [
    {"type": "interval", "duration": {"distance_m": 7000},
     "target": {"kind": "pace", "min_sec_per_km": 330, "max_sec_per_km": 350}}
  ]}
]}
```

**Put the target pace + HR cap in the NAME** (visible on the watch when the athlete selects the workout).

## Rule B — Warmups/Cooldowns = `lap_button` by default

For **real sessions** (intervals, threshold, VO2max, strides, fartlek, M-pace embedded in a LR) that have a warmup/cooldown:
- `warmup`: `Duration(lap_button=True)` — the athlete ends it by pressing lap on reaching the session's starting point (stadium, track, flat road)
- `cooldown`: `Duration(lap_button=True)` — same for the way home

**Why**: with a 1 km distance-based warmup, the athlete reaches the intensity spot at km 0.5 (the warmup and the location do not line up) → the athlete starts the intervals **on the road = dangerous** (cars, uneven ground).

## Rule B-bis — Volume + time target IN THE NAME (corollary of B)

When `lap_button` is used, the athlete has no km target. **Put the volume target + approximate time in the name**: `"Easy ~7 km/40 min then <session> (lap at the track)"`. Compute the time from the average easy pace in the athlete profile.

## Rule B-ter — Warmup MINIMUM 15 min on a quality session

Every warmup of a real session (intervals, threshold, VO2max, fartlek, strides, embedded M-pace) must target **≥ 15 minutes**. The warmup is run at easy pace → it burns no energy, it is just aerobic warming up. < 15 min = incomplete warm-up, injury risk ↑. Later on (peak sessions), going up to 20-25 min is fine. **Never below 15 min**.

## Rule B-quater — Pace target = coaching target ±5 s (watch alerts)

For **every structured pace block** (easy run with a target, fartlek, threshold, M-pace, etc.), widen the DSL `PaceTarget` window by **±5 sec/km** around the coaching target. Garmin then gives an audible alert if the athlete leaves the widened zone (without beeping constantly at the slightest deviation). The workout **NAME** keeps the strict coaching target (e.g. *"4:20-4:25"*) for visibility; the ±5 s tolerance is implicit in the Garmin window.

**Exception**: **strides = `target: None` (no_target)**. Run "relaxed, almost sprinting" by feel. Over 15-80 m, GPS accuracy is too low for useful alerts.

## Rule D — End of session = ALWAYS a lap press (never an automatic end)

**Every** workout pushed to the watch (plain easy runs included) ends with an open `cooldown` step with `Duration(lap_button=True)`. The watch must **never** close the session on its own: the athlete decides when it ends by pressing lap (back home, a bit of extra easy running, a clean stop at the track).

- Quality session with a timed `cd 10'`: the `cooldown lap_button` **is added after** the timed cooldown (2 cooldown steps, Garmin accepts it).
- 1-block easy run (Rule A): distance-based block **then** `cooldown lap_button`.
- **The watch provider's builder (Garmin: `providers/garmin_workout.build_workout`) adds this step automatically** if the DSL does not already end with a `lap_button`. Do not duplicate it by hand, but never rely on it for a DSL written by hand outside the builder.

**Why**: explicit athlete preference (2026-09-11). An automatic end cuts the watch in the middle of the way home or prevents extending; the lap press is the only reliable end signal.

## Rule E — `sync_upcoming_workouts` never guesses a structure

The automatic plan → workout conversion (`plan_to_dsl.convert_planned_workout`) **reads the session description**. It only pushes a quality session if the description contains an explicit structure: `N×D km|m @ <pace|zone letter> r <recovery>` or `X km incl. N min|km @ <pace|letter>`. Otherwise the session is returned in `not_converted` with the reason → push it by hand via `build_and_push_workout`.

**Default filter**: without `include_easy=True`, only sessions that carry quality are pushed (`plan_to_dsl.carries_quality`: tempo / intervals / race, and long runs with an embedded pace block). Plain easy, recovery and long runs are returned in `left_unpushed` — they are run on feel.

**Consequence for writing plan descriptions**: always write quality sessions in this form (e.g. `Q1 Threshold: 5×1 km @ T 4:16-4:20 r 2'`, `Q2 M-pace: 12 km incl. 30 min @ M`). A zone letter alone (`@ M`) is resolved via the profile VDOT.

**Why**: on 2026-09-10 the old heuristic ("total distance − 3.5 km at target pace") turned "10 km incl. 15 min @ M" into a single 7.5 km block at 4:37, with a 2 km distance-based warmup instead of the lap. The session was not runnable as pushed.

## Rule C — Classification before build

Before any build, classify the session:

| Type | DSL format |
|---|---|
| Plain easy run (easy / recovery / jog) | 1 `repeat count=1` step + distance-based `interval` + pace target + final `cooldown lap_button` (Rule D). **NO** warmup or timed cooldown |
| Quality session (intervals, threshold, VO2max, fartlek, strides) | `warmup` lap_button + body + `cooldown` lap_button |
| **Continuous easy** LR (no embedded M-pace) | Treat as a plain easy run = 1 block + final `lap_button` |
| LR **with embedded M-pace or tempo** | Treat as a quality session = lap_button + structured body |

Session types never pushed: `rest` and `strength` (canonical type for strength / physio work; `kiné-renfo` is a legacy alias still accepted).

## Example: easy run + strides

```json
{"sport": "running", "name": "Thu — Easy ~7 km/40 min then 4×80m strides (lap at the track)", "steps": [
  {"type": "warmup", "duration": {"lap_button": true}},
  {"type": "repeat", "count": 4, "steps": [
    {"type": "interval", "duration": {"distance_m": 80}, "target": null},
    {"type": "recovery", "duration": {"seconds": 60}}
  ]},
  {"type": "cooldown", "duration": {"lap_button": true}}
]}
```

## French / English equivalents

The plan parser (`plan_to_dsl`) accepts both languages in session descriptions. This glossary is the reference for the French terms athletes and older plans may use.

| French | English | Notes |
|---|---|---|
| `dont` | `incl.` / `including` | Embedded block: `10 km dont 15 min @ M` = `10 km incl. 15 min @ M`. The parser accepts both; `with` is deliberately NOT accepted ("with 2 km warmup" would be misread as an embedded block) |
| `r 2'` | `rec 2'` / `recovery 2'` | Recovery between reps (`r` works in both languages) |
| EF (endurance fondamentale) | easy run | Easy aerobic pace, Z1-Z2 |
| SL (sortie longue) | long run (LR) | `SL 22 km dont 6 km @ M` = `LR 22 km including 6 km @ M` |
| renfo / kiné-renfo | strength | Session type `strength`; `kiné-renfo` is a legacy alias |
| footing | easy run | |
| allure | pace | |
| VMA | ≈ vVO2max | Maximal aerobic speed |
