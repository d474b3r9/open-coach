"""Onboarding: scan 6 months of watch history to build the athlete profile.

Handles PR detection, VDOT calculation, CTL/ATL/TSB computation,
and training pattern analysis.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from open_coach.models import (
    ActivitySummary,
    AthleteProfile,
    PersonalRecord,
    TrainingPattern,
)
from open_coach.training_load import calculate_load_series, calculate_tss
from open_coach.vdot import HALF_MARATHON_M, MARATHON_M, calculate_vdot

logger = logging.getLogger(__name__)

# Standard race distances with tolerance for detection
_STANDARD_DISTANCES = {
    "1K": (1000, 50),
    "5K": (5000, 100),
    "10K": (10000, 200),
    "half_marathon": (HALF_MARATHON_M, 300),
    "marathon": (MARATHON_M, 500),
}


def merge_personal_records(
    platform_prs: list[PersonalRecord],
    detected_prs: list[PersonalRecord],
) -> list[PersonalRecord]:
    """Merge two PR sources by distance, preferring the watch platform (authoritative).

    For each distance label, returns the platform PR if available, else the
    detected PR. Platform entries take precedence even if the detected one is
    nominally faster, because the platform's split-based timing is what matters.

    Args:
        platform_prs: PRs reported by the watch platform (WatchProvider.personal_records).
        detected_prs: PRs inferred from raw activity totals.

    Returns:
        Combined list, one entry per distance label.
    """
    by_label: dict[str, PersonalRecord] = {pr.distance_label: pr for pr in detected_prs}
    for pr in platform_prs:
        by_label[pr.distance_label] = pr  # the platform wins
    # Stable order: platform label order first, then leftover detected
    order = ["1K", "5K", "10K", "half_marathon", "marathon"]
    return [by_label[k] for k in order if k in by_label]


def detect_personal_records(activities: list[ActivitySummary]) -> list[PersonalRecord]:
    """Detect personal records at standard distances from activity history.

    For each standard distance, finds the fastest activity within tolerance.

    Args:
        activities: List of activity summaries.

    Returns:
        List of detected personal records.
    """
    prs: list[PersonalRecord] = []

    for label, (target_m, tolerance) in _STANDARD_DISTANCES.items():
        candidates = [
            a for a in activities if abs(a.distance_m - target_m) <= tolerance and a.duration_s > 0
        ]
        if not candidates:
            continue

        # Fastest = lowest pace
        best = min(candidates, key=lambda a: a.duration_s / a.distance_m)
        pace = best.duration_s / best.distance_m * 1000  # sec/km

        prs.append(
            PersonalRecord(
                distance_label=label,
                distance_m=best.distance_m,
                time_s=best.duration_s,
                pace_sec_per_km=pace,
                activity_id=best.activity_id,
                date=best.date,
                source="detected",
            )
        )

    return prs


def compute_vdot_from_prs(
    prs: list[PersonalRecord], max_age_days: int = 90
) -> tuple[float | None, str | None]:
    """Calculate VDOT from the best recent personal record.

    Prefers shorter distances (more reliable for VDOT) within the time window.

    Args:
        prs: List of personal records.
        max_age_days: Only consider PRs within this many days.

    Returns:
        Tuple of (vdot, source_description) or (None, None) if no recent PRs.
    """
    cutoff = date.today() - timedelta(days=max_age_days)
    recent = [pr for pr in prs if pr.date >= cutoff]

    if not recent:
        # Fall back to any PR
        recent = prs

    if not recent:
        return None, None

    # Prefer shorter distances for VDOT accuracy (5K > 10K > half > marathon)
    priority = {"1K": 5, "5K": 4, "10K": 3, "half_marathon": 2, "marathon": 1}
    best = max(recent, key=lambda pr: priority.get(pr.distance_label, 0))

    vdot = calculate_vdot(best.distance_m, best.time_s)
    minutes = int(best.time_s // 60)
    secs = int(best.time_s % 60)
    source = f"{best.distance_label} {minutes}:{secs:02d} on {best.date}"

    return vdot, source


def analyze_training_patterns(
    activities: list[ActivitySummary], window_days: int = 180
) -> TrainingPattern | None:
    """Analyze recent training patterns from activity history.

    Args:
        activities: List of activity summaries.
        window_days: Analysis window in days.

    Returns:
        TrainingPattern summary, or None if not enough data.
    """
    cutoff = date.today() - timedelta(days=window_days)
    recent = [a for a in activities if a.date >= cutoff]

    if len(recent) < 4:
        return None

    weeks = window_days / 7
    total_km = sum(a.distance_m / 1000 for a in recent)
    weekly_volume = total_km / weeks
    weekly_freq = len(recent) / weeks

    # Long runs: top 20% by distance
    sorted_by_dist = sorted(recent, key=lambda a: a.distance_m, reverse=True)
    long_runs = sorted_by_dist[: max(1, len(sorted_by_dist) // 5)]
    long_run_avg = sum(a.distance_m / 1000 for a in long_runs) / len(long_runs)

    # Easy pace: median of runs with pace > 5:00/km
    easy_runs = [
        a for a in recent if a.avg_pace_sec_per_km is not None and a.avg_pace_sec_per_km > 300
    ]
    if easy_runs:
        paces = sorted(
            a.avg_pace_sec_per_km for a in easy_runs if a.avg_pace_sec_per_km is not None
        )
        easy_pace = paces[len(paces) // 2]
    else:
        paces_all = [a.avg_pace_sec_per_km for a in recent if a.avg_pace_sec_per_km]
        easy_pace = sum(paces_all) / len(paces_all) if paces_all else 360.0

    return TrainingPattern(
        weekly_volume_km=round(weekly_volume, 1),
        weekly_frequency=round(weekly_freq, 1),
        long_run_avg_km=round(long_run_avg, 1),
        easy_pace_avg_sec_per_km=round(easy_pace, 0),
        analysis_window_days=window_days,
        computed_at=datetime.now(),
    )


def compute_training_load(
    activities: list[ActivitySummary],
    threshold_hr: int = 170,
) -> tuple[float | None, float | None, float | None]:
    """Compute current CTL/ATL/TSB from activity history.

    Args:
        activities: List of activity summaries with HR data.
        threshold_hr: Lactate threshold HR for TSS calculation.

    Returns:
        Tuple of (ctl, atl, tsb) or (None, None, None) if not enough data.
    """
    entries_with_hr = [a for a in activities if a.avg_hr is not None and a.avg_hr > 0]
    if not entries_with_hr:
        return None, None, None

    # Aggregate daily TSS
    daily_tss: dict[date, float] = {}
    for a in entries_with_hr:
        if a.avg_hr is None:  # pragma: no cover — filtered above; narrows type for mypy
            continue
        tss = calculate_tss(a.duration_s, a.avg_hr, threshold_hr)
        daily_tss[a.date] = daily_tss.get(a.date, 0) + tss

    tss_list = sorted(daily_tss.items())
    if not tss_list:
        return None, None, None

    load_series = calculate_load_series(tss_list)
    if not load_series:
        return None, None, None

    final = load_series[-1]
    return final.ctl, final.atl, final.tsb


def build_profile_from_activities(
    activities: list[ActivitySummary],
    personal_records: list[PersonalRecord] | None = None,
) -> AthleteProfile:
    """Build a complete athlete profile from activity history.

    Args:
        activities: List of activity summaries (ideally 6 months).
        personal_records: PRs reported by the watch platform
            (``WatchProvider.personal_records``). Merged on top of the
            activity-inferred PRs — the platform wins per distance because its
            timings come from split detection (no watch-overrun pollution).

    Returns:
        AthleteProfile with PRs, VDOT, patterns, and training load.
    """
    detected = detect_personal_records(activities)
    prs = merge_personal_records(personal_records or [], detected)
    vdot, vdot_source = compute_vdot_from_prs(prs)
    pattern = analyze_training_patterns(activities)
    ctl, atl, tsb = compute_training_load(activities)

    return AthleteProfile(
        vdot=round(vdot, 1) if vdot else None,
        vdot_source=vdot_source,
        personal_records=prs,
        training_pattern=pattern,
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        created_at=datetime.now(),
        onboarding_complete=True,
    )
