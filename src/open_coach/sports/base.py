"""Sport interface and the neutral types shared by every sport.

This module is imported by ``models.py``: it must not import any other
``open_coach`` module.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

SportKey = Literal["running"]
"""Sports with a plugin. Widen together with ``registry._SPORTS`` when adding one."""

OTHER_SPORT: Literal["other"] = "other"
ActivitySport = SportKey | Literal["other"]
"""Sport of a recorded activity: a plugin sport, or ``other`` (counts in load only)."""

TargetKind = Literal["pace", "heart_rate"]
"""Watch-workout target kinds (``workout_dsl.Target``). Extend with power, swim pace…"""

IntensityKind = Literal["pace_sec_per_km", "heart_rate_bpm"]
"""Unit of an ``Intensity`` value; extend (power_w, pace_sec_per_100m…) per sport."""

# Sessions that belong to no sport: excluded from sport volume and completion
# rate. "strength" is canonical; "kine-renfo" / "kiné-renfo" are the legacy
# French names still found in existing plans.
NON_SPORT_WORKOUT_TYPES = frozenset({"rest", "strength", "kine-renfo", "kiné-renfo"})  # fr-ok


class Intensity(BaseModel):
    """A single target or measured intensity, e.g. a pace or a heart rate."""

    kind: IntensityKind
    value: float = Field(gt=0)


class Volume(BaseModel):
    """Training volume of one sport over a period."""

    distance_m: float = 0.0
    duration_s: float = 0.0


class FitnessMarker(BaseModel):
    """The sport's headline fitness number (running: VDOT)."""

    metric: str  # "vdot" for running
    value: float = Field(gt=0)
    source: str | None = None  # e.g. "10K 45:12 on 2026-02-15"


@runtime_checkable
class Sport(Protocol):
    """What the core needs from a sport plugin."""

    key: SportKey
    # FitnessMarker.metric of the sport (running: "vdot").
    fitness_metric: str
    # Headline weekly volume shown in plans: distance (running) or duration.
    volume_metric: Literal["distance", "duration"]
    # Session types of this sport (``PlannedWorkout.workout_type`` values).
    workout_types: frozenset[str]
    # Session types that carry quality and are pushed to the watch.
    quality_types: frozenset[str]
    # Watch-workout target kinds the sport accepts.
    target_kinds: frozenset[TargetKind]
    # Typical speed, to estimate the duration of a distance-based workout step.
    default_speed_mps: float

    def format_intensity(self, intensity: Intensity) -> str:
        """Human-readable intensity, e.g. ``5:30/km``."""
        ...
