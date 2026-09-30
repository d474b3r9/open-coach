"""Onboarding: scan 6 months of watch history to build the athlete profile.

Each sport plugin builds its own block (records, fitness, pattern —
``Sport.build_profile``); the training load counts every activity.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from open_coach.models import ActivitySummary, AthleteProfile, PersonalRecord
from open_coach.sports.base import SportKey
from open_coach.sports.registry import get_sport, supported_sports
from open_coach.training_load import calculate_load_series, calculate_tss

logger = logging.getLogger(__name__)


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
    personal_records: dict[SportKey, list[PersonalRecord]] | None = None,
) -> AthleteProfile:
    """Build a complete athlete profile from activity history.

    Args:
        activities: Activity summaries of every sport (ideally 6 months).
        personal_records: Records reported by the watch platform, per sport
            (``WatchProvider.personal_records``).

    Returns:
        AthleteProfile with one block per sport found in the history (records,
        fitness, pattern — built by the sport plugin) and the training load of
        every activity.
    """
    records = personal_records or {}
    sports = {
        key: get_sport(key).build_profile(
            [a for a in activities if a.sport == key], records.get(key, [])
        )
        for key in supported_sports()
        if any(a.sport == key for a in activities) or records.get(key)
    }
    ctl, atl, tsb = compute_training_load(activities)

    return AthleteProfile(
        sports=sports,
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        created_at=datetime.now(),
        onboarding_complete=True,
    )
