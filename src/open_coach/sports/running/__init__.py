"""Running plugin: Daniels VDOT, pace zones and running session types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from open_coach.sports.base import FitnessMarker, Intensity, SportKey, TargetKind
from open_coach.vdot import format_pace

if TYPE_CHECKING:
    from open_coach.models import AthleteProfile

RUNNING: SportKey = "running"
VDOT_METRIC = "vdot"


class RunningSport:
    key: SportKey = RUNNING
    fitness_metric = VDOT_METRIC
    volume_metric: Literal["distance", "duration"] = "distance"
    workout_types = frozenset(
        {"easy", "long_run", "recovery", "tempo", "interval", "intervals", "fartlek", "race"}
    )
    quality_types = frozenset({"tempo", "interval", "intervals", "fartlek"})
    target_kinds: frozenset[TargetKind] = frozenset({"pace", "heart_rate"})
    default_speed_mps = 1000 / 300  # 5:00/km

    def format_intensity(self, intensity: Intensity) -> str:
        if intensity.kind == "pace_sec_per_km":
            # round() before formatting: format_pace itself truncates.
            return f"{format_pace(round(intensity.value))}/km"
        return f"{round(intensity.value)} bpm"


def vdot_of(profile: AthleteProfile | None) -> float | None:
    """The athlete's running VDOT, or None if unknown."""
    if profile is None:
        return None
    sp = profile.sports.get(RUNNING)
    if sp is None or sp.fitness is None or sp.fitness.metric != VDOT_METRIC:
        return None
    return sp.fitness.value


def set_vdot(profile: AthleteProfile, vdot: float, source: str | None = None) -> None:
    """Record the running VDOT on *profile* (creates the running block if needed)."""
    profile.sport_profile(RUNNING, create=True).fitness = FitnessMarker(
        metric=VDOT_METRIC, value=vdot, source=source
    )


def avg_pace_sec_per_km(duration_s: float, distance_m: float) -> float | None:
    """Average pace in sec/km, or None when the distance is zero/invalid."""
    if distance_m <= 0:
        return None
    return duration_s / (distance_m / 1000.0)


def pace(sec_per_km: float | None) -> Intensity | None:
    """Wrap a pace in sec/km as an ``Intensity`` (None passes through)."""
    return None if sec_per_km is None else Intensity(kind="pace_sec_per_km", value=sec_per_km)


def pace_of(intensity: Intensity | None) -> float | None:
    """The pace in sec/km carried by *intensity*, or None if it is not a pace."""
    if intensity is None or intensity.kind != "pace_sec_per_km":
        return None
    return intensity.value
