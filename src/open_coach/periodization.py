"""Periodization building blocks shared by every sport (no I/O).

A sport's plan builder (``Sport.generate_plan``) picks its own taper / peak
lengths, volume units and sessions; the week structure, the volume
progression and the day placement come from here.
"""

from __future__ import annotations

from typing import Literal

from open_coach.models import TrainingConstraints

# Weekday name → index (Monday = 0)
DAY_INDEX: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

WeekType = Literal["base", "build", "peak", "taper", "recovery"]


# ── Week type assignment ───────────────────────────────────────────────────────


def assign_week_types(total_weeks: int, taper: int, peak: int) -> list[WeekType]:
    """Assign a type to each training week (chronological order).

    On short horizons (total_weeks < taper + peak) the taper is shortened
    first, then the peak, so the plan never exceeds total_weeks.
    """
    if taper + peak > total_weeks:
        taper = max(1, total_weeks - peak)
        peak = max(0, total_weeks - taper)
    build_base_count = max(0, total_weeks - taper - peak)

    types: list[WeekType] = []

    for i in range(build_base_count):
        if (i + 1) % 4 == 0:
            types.append("recovery")
        elif i < build_base_count // 2:
            types.append("base")
        else:
            types.append("build")

    for _ in range(peak):
        types.append("peak")

    for _ in range(taper):
        types.append("taper")

    return types


# ── Volume calculation ─────────────────────────────────────────────────────────


def volume_for_week(
    i: int,
    week_type: WeekType,
    start: float,
    peak: float,
    week_types: list[WeekType],
) -> float:
    """Target weekly volume, in the unit of *start* / *peak* (km, hours…)."""
    total = len(week_types)
    n_taper = sum(1 for t in week_types if t == "taper")
    n_peak = sum(1 for t in week_types if t == "peak")
    build_end = total - n_taper - n_peak

    if week_type == "taper":
        taper_i = i - build_end - n_peak
        taper_fracs = [0.80, 0.65, 0.45]
        frac = taper_fracs[min(taper_i, len(taper_fracs) - 1)]
        return round(peak * frac, 1)

    if week_type == "peak":
        return round(peak, 1)

    # Base / build / recovery: linear progression from start to peak
    progress = i / max(1, build_end - 1) if build_end > 1 else 1.0
    expected = start + (peak - start) * min(1.0, progress)

    if week_type == "recovery":
        return round(expected * 0.70, 1)

    return round(expected, 1)


def max_minutes_for_day(day_idx: int, constraints: TrainingConstraints) -> int | None:
    """Session duration cap for a weekday index (Saturday/Sunday use the weekend cap)."""
    if day_idx >= 5:
        return constraints.max_weekend_minutes
    return constraints.max_weekday_minutes


def available_day_indices(constraints: TrainingConstraints) -> list[int]:
    """Sorted weekday indices from constraints, or default Mon/Wed/Fri/Sun."""
    if constraints.available_days:
        indices = sorted(
            DAY_INDEX[d.lower()] for d in constraints.available_days if d.lower() in DAY_INDEX
        )
    else:
        indices = [0, 2, 4, 6]  # Mon, Wed, Fri, Sun

    if constraints.max_sessions_per_week:
        indices = indices[: constraints.max_sessions_per_week]

    return indices
