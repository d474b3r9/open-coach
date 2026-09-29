# Athlete profile — template

> Replace every `<...>` placeholder with your own values. The skill `entraineur` reads this file at the start of every coaching session and applies the rules in it. **Do not commit this file** — it lives in the gitignored `plans/` directory.

## 1. Profile

- **Name / nickname**: `<your-name>`
- **Date of birth**: `<YYYY-MM-DD>`
- **Sex**: `<M | F | NB>`
- **Years of regular running**: `<years>`
- **Job / schedule constraints**: `<short description>`

## 2. Current metrics

> Update after each test or recalibration event. Date the row to keep history.

| Metric | Value | Source / date |
|---|---|---|
| VDOT (Daniels) | `<VDOT>` | `<race or test, YYYY-MM-DD>` |
| Max HR (measured) | `<bpm>` | `<test or observed max YYYY-MM-DD>` |
| Resting HR | `<bpm>` | `<average of last 7 mornings>` |
| Weight | `<kg>` | `<YYYY-MM-DD>` |
| FTP / threshold HR | `<bpm>` | `<test or estimate>` |

### Derived target paces (Daniels VDOT)

| Pace | Min/km | Source |
|---|---|---|
| Easy (E) | `<m:ss-m:ss>` | Daniels Easy zone |
| Marathon (M) | `<m:ss>` | Daniels M-pace |
| Threshold (T) | `<m:ss-m:ss>` | Daniels T-pace |
| Interval (I) | `<m:ss-m:ss>` | Daniels I-pace |
| Repetition (R) | `<m:ss-m:ss>` | Daniels R-pace |

## 3. Race calendar

> List your target races. The skill `entraineur` uses these dates to structure plans (base/build/peak/taper phases, test placement, post-race breaks).

| Date | Distance | Race | Status | Target time |
|---|---|---|---|---|
| `<YYYY-MM-DD>` | `<10K | half | marathon | ultra Xkm>` | `<race name>` | `<A | B | rehearsal>` | `<HH:MM>` |

A = main goal race, B = secondary, rehearsal = dress rehearsal.

## 4. Physical constraints

> List structural constraints (past injuries, weak spots, limitations). The skill `entraineur` adapts sessions accordingly (no hills if a tendon is fragile, etc.).

- **Injury history**: `<injury, side, year>`
- **Weak spots**: `<areas to monitor>`
- **To avoid**: `<types of effort to rule out>`
- **Mandatory practice**: `<strength protocol, frequency>`

## 5. Volume & availability

| Field | Value |
|---|---|
| Max weekly volume (peak) | `<km>` km/week |
| Comfortable base weekly volume | `<km>` km/week |
| Max running days / week | `<n>` |
| Week convention | `<EU: Monday = day 1 | US: Sunday = day 1>` |

### Availability per day (typical slot)

| Day | Max duration | Note |
|---|---|---|
| Monday | `<min>` | `<recurring constraint, if any>` |
| Tuesday | `<>` | |
| Wednesday | `<>` | |
| Thursday | `<>` | |
| Friday | `<>` | |
| Saturday | `<>` | |
| Sunday | `<min>` | `<e.g. long run slot>` |

## 6. Race nutrition preferences

> The skill `entraineur` proposes gel/hydration plans aligned with these preferences without challenging them every session.

- **Preferred gel format**: `<gel | liquid | bar>` — a single format
- **Starter gel**: `<yes, T-x | no>`
- **Solid food during races**: `<yes | no | depending on terrain>`
- **Hydration**: `<water | isotonic | mix, concentration>`
- **Ultra vest setup**: `<number of flasks, contents>`
- **Caffeinated**: `<number and timing | none>`
- **Digestion preferences**: `<intolerances, formats to avoid, validated brands>`

### Typical road marathon scheme

`<gel every X km / Y g/h target / total count>`

### Typical ultra scheme with vest

`<gel every X min / Y g/h target / isotonic flask / refill at aid stations>`

## 7. Strength & conditioning

| Block | Day | Duration | Focus |
|---|---|---|---|
| `<block 1>` | `<day>` | `<min>` | `<area or protocol>` |
| `<block 2>` | `<day>` | `<min>` | `<area or protocol>` |

## 8. Personal anti-patterns (settled preferences)

> The skill `entraineur` must never propose these things again:

- ❌ `<thing never to propose again>`
- ❌ `<...>`
- ❌ `<...>`

## 9. Free notes

`<free field for anything that does not fit in the sections above>`
