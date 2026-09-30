"""Running profile from activity history: personal records, VDOT, training pattern."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from open_coach.models import ActivitySummary, PersonalRecord, SportProfile, TrainingPattern
from open_coach.sports.base import FitnessMarker
from open_coach.sports.running import VDOT_METRIC, avg_pace_sec_per_km, pace
from open_coach.sports.running.vdot import HALF_MARATHON_M, MARATHON_M, calculate_vdot

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

        prs.append(
            PersonalRecord(
                distance_label=label,
                distance_m=best.distance_m,
                time_s=best.duration_s,
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
    weekly_distance = sum(a.distance_m for a in recent) / weeks
    weekly_duration = sum(a.duration_s for a in recent) / weeks
    weekly_freq = len(recent) / weeks

    # Long runs: top 20% by distance
    sorted_by_dist = sorted(recent, key=lambda a: a.distance_m, reverse=True)
    long_runs = sorted_by_dist[: max(1, len(sorted_by_dist) // 5)]
    long_run_avg = sum(a.distance_m for a in long_runs) / len(long_runs)
    long_run_dur = sum(a.duration_s for a in long_runs) / len(long_runs)

    # Easy pace: median of runs with pace > 5:00/km
    all_paces = [p for a in recent if (p := avg_pace_sec_per_km(a.duration_s, a.distance_m))]
    easy_paces = sorted(p for p in all_paces if p > 300)
    if easy_paces:
        easy_pace = easy_paces[len(easy_paces) // 2]
    else:
        easy_pace = sum(all_paces) / len(all_paces) if all_paces else 360.0

    return TrainingPattern(
        weekly_distance_m=round(weekly_distance, -2),
        weekly_duration_s=round(weekly_duration, 0),
        weekly_frequency=round(weekly_freq, 1),
        long_session_avg_distance_m=round(long_run_avg, -2),
        long_session_avg_duration_s=round(long_run_dur, 0),
        easy_intensity=pace(round(easy_pace, 0)),
        analysis_window_days=window_days,
        computed_at=datetime.now(),
    )


def build_running_profile(
    runs: list[ActivitySummary], platform_prs: list[PersonalRecord]
) -> SportProfile:
    """Records, VDOT and training pattern from running activities.

    The platform's own PRs are merged on top of the activity-inferred ones —
    the platform wins per distance because its timings come from split
    detection (no watch-overrun pollution).
    """
    prs = merge_personal_records(platform_prs, detect_personal_records(runs))
    vdot, vdot_source = compute_vdot_from_prs(prs)
    profile = SportProfile(personal_records=prs, training_pattern=analyze_training_patterns(runs))
    if vdot:
        profile.fitness = FitnessMarker(
            metric=VDOT_METRIC, value=round(vdot, 1), source=vdot_source
        )
    return profile
