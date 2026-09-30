"""Heart-rate helpers shared by every sport.

Karvonen ranges and resting / max HR estimation from activity history. Each
sport defines its own zones on top (running: ``sports/running/zones.py``).
"""

from __future__ import annotations

from open_coach.models import ActivitySummary, HRRange
from open_coach.sports.running import RUNNING, avg_pace_sec_per_km


def karvonen_range(resting_hr: int, max_hr: int, low_pct: float, high_pct: float) -> HRRange:
    """Heart-rate range at *low_pct*-*high_pct* of the heart-rate reserve (Karvonen).

    Target HR = resting_hr + (max_hr - resting_hr) * intensity_fraction.
    """
    hrr = max_hr - resting_hr
    return HRRange(
        min_bpm=round(resting_hr + hrr * low_pct), max_bpm=round(resting_hr + hrr * high_pct)
    )


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
        sec_per_km = avg_pace_sec_per_km(a.duration_s, a.distance_m)
        if (
            a.sport == RUNNING
            and a.avg_hr is not None
            and a.duration_s > 1800
            and sec_per_km is not None
            and sec_per_km > 300
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
