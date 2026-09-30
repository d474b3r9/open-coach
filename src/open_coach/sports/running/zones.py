"""Daniels running zones: pace from VDOT, heart rate from Karvonen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from open_coach.models import HRRange
from open_coach.sports.running.vdot import format_pace, training_paces
from open_coach.zones import karvonen_range

if TYPE_CHECKING:
    from open_coach.models import AthleteProfile


class PaceRange(BaseModel):
    """Pace range in seconds per kilometer."""

    min_pace_sec_per_km: float  # faster (lower number)
    max_pace_sec_per_km: float  # slower (higher number)


class ZoneInfo(BaseModel):
    """Combined pace and HR info for a training zone."""

    pace: PaceRange | None = None
    hr: HRRange | None = None


class TrainingZones(BaseModel):
    """Training zones derived from VDOT and/or HR."""

    easy: ZoneInfo
    marathon: ZoneInfo
    threshold: ZoneInfo
    interval: ZoneInfo
    repetition: ZoneInfo


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

    zones = {
        zone_name: ZoneInfo(hr=karvonen_range(resting_hr, max_hr, low_pct, high_pct))
        for zone_name, (low_pct, high_pct) in _HR_ZONE_PERCENTAGES.items()
    }

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


def zones_payload(profile: AthleteProfile | None, vdot: float) -> dict[str, Any]:
    """Tool payload: Daniels pace zones for *vdot*, plus Karvonen HR when the profile allows."""
    zones = pace_zones_from_vdot(vdot)
    hr_source: dict[str, Any] | None = None
    if (
        profile is not None
        and profile.resting_hr is not None
        and profile.max_hr is not None
        and profile.resting_hr < profile.max_hr
    ):
        zones = merge_zones(zones, hr_zones_karvonen(profile.resting_hr, profile.max_hr))
        hr_source = {
            "resting_hr": profile.resting_hr,
            "max_hr": profile.max_hr,
            "method": "karvonen",
        }

    result: dict[str, Any] = {"vdot": round(vdot, 1), "zones": {}}
    for zone_name in ["easy", "marathon", "threshold", "interval", "repetition"]:
        zone_info = getattr(zones, zone_name)
        result["zones"][zone_name] = {
            "pace": (
                f"{format_pace(zone_info.pace.min_pace_sec_per_km)}"
                f" - {format_pace(zone_info.pace.max_pace_sec_per_km)}/km"
            )
            if zone_info.pace
            else None,
            "hr": (f"{zone_info.hr.min_bpm}-{zone_info.hr.max_bpm} bpm" if zone_info.hr else None),
        }

    if hr_source is not None:
        result["hr_source"] = hr_source
    else:
        result["hint"] = (
            "HR zones unavailable — set resting_hr and max_hr via "
            "update_athlete_profile or run bootstrap_athlete_profile."
        )
    return result
