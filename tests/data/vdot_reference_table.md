# VDOT reference table (test fixture)

Hermetic fixture for `tests/test_plan_vdot_tables.py`. The values below were
generated from `open_coach.vdot.predict_time` — the test re-derives them and
fails if `vdot.py` output drifts from this committed snapshot (or vice versa).

| VDOT | 5K | 10K | Half | Marathon | Pace 10K |
|------|-----|------|------|----------|------------|
| 40 | 24:06 | 50:00 | 1:50:53 | 3:49:37 | 5:00/km |
| **50 (target)** | 19:56 | 41:19 | 1:31:31 | 3:10:39 | 4:07/km |
