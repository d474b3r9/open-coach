"""Training zone calculations from VDOT and heart rate data.

Provides pace zones (Daniels) and HR zones (Karvonen) with
automatic HR estimation from watch data or activity history.
"""

from __future__ import annotations

from open_coach.models import (
    ActivitySummary,
    HRRange,
    PaceRange,
    TrainingZones,
    ZoneInfo,
)
from open_coach.vdot import training_paces


def pace_zones_from_vdot(vdot: float) -> TrainingZones:
    """Calculate Daniels pace zones from VDOT.

    Args:
        vdot: The athlete's VDOT value.

    Returns:
        TrainingZones with pace ranges for each zone.
    """
    paces = training_paces(vdot)

    zones = {}
    for zone_name, (fast_pace, slow_pace) in paces.items():
        zones[zone_name] = ZoneInfo(
            pace=PaceRange(min_pace_sec_per_km=fast_pace, max_pace_sec_per_km=slow_pace)
        )

    return TrainingZones(**zones)


# Karvonen HR zone percentages (of Heart Rate Reserve)
_HR_ZONE_PERCENTAGES = {
    "easy": (0.59, 0.74),
    "marathon": (0.74, 0.84),
    "threshold": (0.84, 0.88),
    "interval": (0.88, 0.95),
    "repetition": (0.95, 1.00),
}


def hr_zones_karvonen(resting_hr: int, max_hr: int) -> TrainingZones:
    """Calculate HR zones using the Karvonen (Heart Rate Reserve) method.

    Target HR = resting_hr + (max_hr - resting_hr) * intensity_fraction

    Args:
        resting_hr: Resting heart rate in BPM.
        max_hr: Maximum heart rate in BPM.

    Returns:
        TrainingZones with HR ranges for each zone.

    Raises:
        ValueError: If resting_hr >= max_hr.
    """
    if resting_hr >= max_hr:
        raise ValueError(f"Resting HR ({resting_hr}) must be less than max HR ({max_hr}).")

    hrr = max_hr - resting_hr

    zones = {}
    for zone_name, (low_pct, high_pct) in _HR_ZONE_PERCENTAGES.items():
        low_hr = round(resting_hr + hrr * low_pct)
        high_hr = round(resting_hr + hrr * high_pct)
        zones[zone_name] = ZoneInfo(hr=HRRange(min_bpm=low_hr, max_bpm=high_hr))

    return TrainingZones(**zones)


def merge_zones(pace_zones: TrainingZones, hr_zones: TrainingZones) -> TrainingZones:
    """Merge pace zones and HR zones into combined TrainingZones.

    Args:
        pace_zones: Zones with pace data.
        hr_zones: Zones with HR data.

    Returns:
        TrainingZones with both pace and HR for each zone.
    """
    merged = {}
    for zone_name in ["easy", "marathon", "threshold", "interval", "repetition"]:
        pace_info = getattr(pace_zones, zone_name)
        hr_info = getattr(hr_zones, zone_name)
        merged[zone_name] = ZoneInfo(pace=pace_info.pace, hr=hr_info.hr)
    return TrainingZones(**merged)


def estimate_resting_hr(activities: list[ActivitySummary]) -> int | None:
    """Estimate resting HR from the lowest HR observed in easy/long activities.

    Takes the minimum avg_hr from easy-paced runs (> 30 min) and subtracts
    a fixed 60 bpm offset (easy exercise HR is typically resting + 50-70 bpm)
    as a rough proxy for resting HR.

    Args:
        activities: List of recent activity summaries.

    Returns:
        Estimated resting HR, or None if not enough data.
    """
    # Filter for easy/long runs (> 30 min, pace > 5:00/km = 300 sec/km)
    easy_hrs = []
    for a in activities:
        if (
            a.avg_hr is not None
            and a.duration_s > 1800
            and a.avg_pace_sec_per_km is not None
            and a.avg_pace_sec_per_km > 300
        ):
            easy_hrs.append(a.avg_hr)

    if len(easy_hrs) < 3:
        return None

    easy_hrs.sort()
    # Take the minimum observed — it's a rough proxy, not actual resting HR
    # Subtract ~40% of the difference to estimated resting (very rough)
    min_exercise_hr = easy_hrs[0]
    # Exercise easy HR is typically resting + 50-70bpm
    estimated = max(40, min_exercise_hr - 60)
    return estimated


def estimate_max_hr(activities: list[ActivitySummary]) -> int | None:
    """Estimate max HR from the highest HR observed in hard activities.

    Uses the 95th percentile of max_hr from interval/race efforts.

    Args:
        activities: List of activity summaries (ideally 6+ months).

    Returns:
        Estimated max HR, or None if not enough data.
    """
    max_hrs = [a.max_hr for a in activities if a.max_hr is not None and a.max_hr > 100]

    if len(max_hrs) < 3:
        return None

    max_hrs.sort()
    # 95th percentile to avoid sensor glitches
    idx = min(int(len(max_hrs) * 0.95) - 1, len(max_hrs) - 1)
    idx = max(idx, 0)
    return max_hrs[idx]
