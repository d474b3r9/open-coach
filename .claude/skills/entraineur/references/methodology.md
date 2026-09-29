# Coaching methodology — universal principles

Reference loaded by the `entraineur` skill when a methodology rule must be applied.

## 1. Daniels VDOT

Every pace derives from VDOT (VO2max equivalent). **NEVER hardcode a pace** — always start from `coach://profile` or the athlete profile. When VDOT changes, every pace moves in cascade.

Daniels reference tables (read from `vdot.training_paces(vdot)` or the athlete profile, never inline here):

| Pace | Description |
|---|---|
| Easy (E) | ≈ +30% of 5K race time, aerobic base |
| Marathon (M) | M-pace |
| Threshold (T) | T-pace, threshold pace |
| Interval (I) | I-pace, VO2max |
| Repetition (R) | R-pace, economy/speed |

**Recalibrate VDOT**:
- After every official race or timed all-out test
- Not after a plain long run or a fartlek
- Not after a failed session (cause = fatigue, not VDOT regression)

**Edge cases**:
- Race in heatwave conditions (T° > 22°C): do not recalibrate downward — performance is degraded by heat, not by VDOT
- DNF: no recalibration — VDOT remains valid, it is the execution that failed

**Prefer the longest recent race** for the baseline (10K > 5K in reliability for a marathon).

## 2. 80/20

80% of weekly volume at easy pace (Easy, Z1-Z2). 20% at intensity (T-pace, M-pace, I-pace, R-pace). Strict ratio — most amateur runners run their easy runs too fast, which disrupts recovery and sinks quality sessions.

## 3. CTL progression +5/week max

Chronic load (CTL) must not climb by more than 5 points per week. Beyond that: injury risk and chronic fatigue. Derived rule: weekly volume never increases by more than ~10% from one week to the next.

## 4. Recovery -25 % volume every 4 cycles

Every 4 weeks, a **recovery week**: volume -25%, lighter quality (moderate fartlek instead of intervals). Recovery is where adaptation happens. Skipping a recovery week → progress plateaus after 8-10 weeks max.

## 5. Standard plan structure

| Phase | Typical duration | Volume | Focus |
|---|---|---|---|
| Base | 3-4 wk | progressive (+10%/wk max) | Aerobic + light threshold |
| Build | 4-5 wk | peak -10 % | Specificity (M-pace, race pace) |
| Peak | 2-3 wk | peak | Race-specific endurance |
| Taper | 1-2 wk | -50 % of peak at the end | Sharpening |

Concrete volumes in km/week derived from the `Max weekly volume (peak)` ceiling read from the athlete profile:

| Phase | Weekly (as % of peak) |
|---|---|
| Return after a break | 50-65 % |
| Base | 65-80 % |
| Build | 80-100 % |
| Peak | 95-100 % |
| Taper | 50 % of peak at the end |

### Typical week structure (Mon → Sun, EU convention)

| Day | Type |
|---|---|
| Monday | Easy run + strength (duration per availability in the athlete profile) |
| Tuesday | Quality 1 — threshold / T-pace / VO2max depending on phase |
| Wednesday | Short easy run or rest |
| Thursday | Quality 2 — M-pace / race-pace specific |
| Friday | Easy + strength |
| Saturday | Rest |
| Sunday | Long run (LR) with gut training |

Adapt to the week convention stated in the profile (EU: Monday = day 1; US: Sunday = day 1).

## 6. Tests and milestones in a plan

### Placement rules

- **M-pace test**: 4-6 wk before the target race
- **10K test**: middle of the Build block (mid-cycle)
- **Dress rehearsal**: 3 wk before the target race (long LR with race nutrition format)
- **No duplicates**: one test per purpose. No separate "calibration + validation" if the gap is < 3 wk.

### Anti-pattern — hypothetical questions

When the athlete asks "so I would do X?" → it is a **question**, not a decision. **Always clarify before executing** a plan change. A hypothetical question never triggers an immediate edit.

## 7. Preparing a 10K test inside a marathon block

**Critical rule**: an all-out 10K test requires paces (I-pace / 10K-pace) that are NEVER trained in a classic marathon build (easy + threshold + M-pace). Without VO2max + race-pace preparation, the test underestimates VDOT by 1-2 points.

### Typical pre-test structure (3 weeks before)

| Week | Focus | Typical session |
|---|---|---|
| **T-2** (Build n) | VO2max primer | 3×1km T + 6×400m @ I-pace r=200m jog |
| **T-1** (Build n+1) | Full VO2max + race pace | Tue: 5×1km @ I-pace r=2'30 / Thu: 3×2km @ 10K pace r=2'30 |
| **T** (test week) | Light taper + opener | Tue: 2 km wu + 5×400m @ 10K pace r=200m jog + 2 km cd / Sat: 4 km + 4 strides |

**Keep the LR with M-pace** over these 3 weeks to preserve marathon specificity.

**When NOT to apply**:
- M-pace test (instead of 10K) → no VO2max prep needed, M-pace is already trained
- Test over a distance > half marathon → aerobic work is already in place

## 8. Post-race recovery

| Race | Break |
|---|---|
| 10K | 3-4 easy days |
| Half | 1 easy week |
| Marathon | **2 full weeks** (zero quality) |
| Ultra > 50 km | **3 full weeks** (zero structure, W+1 = 0 km) |

### Overload signals to watch

- Resting HR > +5 bpm vs baseline = fatigue signal, remove the week's quality
- HRV declining > 7 days = same
- Sleep score degraded over 3 consecutive nights = same
- "Heavy" feeling on 2 easy runs in a row = physical signal before the data signal

## 9. Safeguards (when to downgrade / cancel / re-target)

### Downgrade a session

If on the morning of the quality session:
- Resting HR +5 → run the session as a "moderate fartlek" (free pace, no splits)
- Tendon tightness → cancel the quality, easy run instead
- Sleep < 6 h or high stress → -1 rep, pace +2"/km

### Re-target a race goal

| Signal | Action |
|---|---|
| Mid-block 10K test missed (time > current VDOT +1 sec/km) | Loosen the goal time by 3 to 5 min (slower target) |
| Dress rehearsal failed (wall or GI breakdown) | Keep goal time, review nutrition |
| Heatwave on race day (T° > 18°C for a marathon) | +5"/km on the target |
| Injury during the build | Revise the goal toward "finish" over time |
