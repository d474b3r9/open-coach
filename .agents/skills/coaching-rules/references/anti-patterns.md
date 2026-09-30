# Anti-patterns + physical protocols

Reference loaded by the `coaching-rules` skill for things to NEVER do and for specific strength / nutrition protocols.

## Universal anti-patterns

- ❌ **No duplicate tests**. One test per purpose. If two tests are < 3 wk apart, drop the less critical one.
- ❌ **No VO2max without strength work** behind it (the nervous system + tendons must keep up).
- ❌ **Never execute on a hypothetical question** ("so I would do X?"). Clarify first.
- ❌ **No Garmin SSO retry** during a lockout (rate limit 48 h+, per account). Recovery via `scripts/garmin_re_auth.py`.
- ❌ **No hardcoded pace** — always derive from VDOT.

Also read the athlete profile § "Personal anti-patterns" for the athlete's fixed preferences (respect them without re-debating).

## Athlete constraints — standard patterns

No constraint is coded here. Read `plans/athlete-profile.md` § "Physical constraints" and § "Volume & availability", then apply.

Standard patterns to recognise if present in the profile:

| Profile pattern | Plan adaptation |
|---|---|
| Fragile tendons (Achilles, plantar…) | No repeated hills; eccentric strength mandatory (Alfredson); avoid steep downhills |
| Fragile ankles | Ankle proprioception work mandatory; avoid uneven ground at intensity |
| Knees | Limit sustained downhill; eccentric quad/glute strength |
| IT band / SI joint | Glute med strength; avoid rapid volume build-ups |
| Max weekly volume (peak) | Cap Build and Peak at this value, never exceed it |
| Session cap on day X (limited work/personal slot) | Only schedule sessions that fit in that slot; move long ones if there is a conflict |

## Strength — standard protocols

No specific protocol is coded here. Read the athlete profile § "Strength & conditioning" and § "Physical constraints". Standard patterns:

### Achilles tendon / calves block (15-20 min)

For runners with a history of Achilles / soleus / plantar fascia issues:
1. **Single-leg calf raise, straight knee** (gastrocnemius): 3×12 per side, slow lowering 3-4"
2. **Single-leg calf raise, bent knee** (soleus): 3×12 per side, slow lowering 3-4"
3. Eccentric calf drops on a step: 3×10 per leg
4. Gastrocnemius + soleus stretches: 2×30" each
5. Plantar fascia rolling: 2×60" per foot

Differentiate straight knee (gastrocnemius) / bent knee (soleus) — the soleus bears 6-8× body weight when running and is usually under-trained.

### Ankle / posterior chain block (25-30 min)

**Posterior chain + eccentric** (while fresh):
1. **Single-leg chair step-up (combo)**: 3×8 per side — 2" up, 4" down without touching the heel
2. **Slow Bulgarian split squat**: 3×8 per side — 4" down
3. **Single-leg glute bridge**: 3×8 per side

**Ankle / proprioception** (afterwards):
4. Single-leg balance, eyes closed: 3×30" per side
5. Bosu / balance cushion: 3×45" if available
6. Two-foot hops in place: 3×15
7. Single-leg hops (lateral + forward/back): 2×10 each
8. Ankle resistance band (4 directions): 2×15
9. Ankle mobility stretches: 2×30"

Do the posterior chain **before** proprioception (proprioception at the end of the block tolerates neuromuscular fatigue better).

### Injury-prevention rule

| Signal | Action |
|---|---|
| Tendon pain 3-4/10 during effort | Switch to isometric (5×45s), no eccentric |
| Tightness persisting > 24 h after the session | Remove strength work for the week, -20 % running volume |
| Morning pain > 4/10 | Rest 48 h, see a doctor if it persists 5 days |
| Established tendinitis | STOP the plan, physio/doctor |

## Race nutrition — standard patterns

No preference is coded here. Read the athlete profile § "Race nutrition preferences" and apply. Standard patterns:

| Event type | Generic scheme |
|---|---|
| Road marathon | Gel every 4-5 km aligned with aid stations → ~70-90 g/h. Caffeinated in the 2nd half. Sports drink when offered. |
| Ultra with vest | Concentrated sports drink + plain water in 2 flasks. Gel every 35-50 min depending on format. Aid stations for solids if technical trail. |
| Long technical trail with elevation | Solids tolerated (banana, rice cake) in addition to gels on slow sections. |
| Half / 10K | 1 gel 15 min before the start if duration > 1 h, otherwise nothing. |

### Gut training (mandatory prerequisite)

Any plan using gels in a race includes progressive gut training on long runs:
- Base: 50-60 g/h
- Build: 70-80 g/h
- Peak / dress rehearsal: 85-90 g/h (actual race format)

The gut adapts in 4-6 weeks. Without gut training, dense formats (concentrated gels, sports drink) cause GI issues.

### Nutrition anti-patterns to respect (read from the profile)

The profile may list fixed preferences (e.g. "never a starter gel", "no solids on flat terrain", "single gel format X g"). **Respect them without re-debating**: these preferences come from the athlete's empirical feedback.
