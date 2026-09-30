"""Sport interface and the neutral types shared by every sport.

This module is imported by ``models.py``: it must not import any other
``open_coach`` module at runtime (type-only imports are fine).

Adding a sport: implement ``Sport`` in ``sports/<key>/`` and register it in
``registry._SPORTS``; ``tests/test_sport_contract.py``
then runs the shared scenarios against it. See AGENTS.md "Adding a sport".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import AfterValidator, BaseModel, Field

if TYPE_CHECKING:
    from open_coach.models import (
        ActivitySummary,
        AdaptiveRecommendation,
        AthleteProfile,
        Language,
        PersonalRecord,
        PlannedWorkout,
        RaceReadiness,
        RecoveryAssessment,
        SportProfile,
        TrainingConstraints,
        TrainingGoal,
        TrainingPlan,
    )
    from open_coach.workout_dsl import DSLWorkout


def _registered_sport(value: str) -> str:
    from open_coach.sports.registry import is_registered, supported_sports

    if not is_registered(value):
        raise ValueError(f"Unknown sport {value!r}. Supported: {', '.join(supported_sports())}")
    return value


SportKey = Annotated[str, AfterValidator(_registered_sport)]
"""Key of a registered sport plugin (``registry``), e.g. ``"running"``."""

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


@dataclass(frozen=True)
class Conversion:
    """Result of a plan session → watch workout conversion."""

    dsl: DSLWorkout | None
    reason: str | None = None  # populated when dsl is None

    @property
    def ok(self) -> bool:
        return self.dsl is not None


class RaceModel(Protocol):
    """Race-day capability of a sport: predictions, pacing, readiness.

    Methods return the tool payload; an ``{"error": ...}`` dict when the
    athlete lacks the data (e.g. no fitness marker yet).
    """

    def predictions(self, profile: AthleteProfile, goal: TrainingGoal | None) -> dict[str, Any]: ...

    def pacing(
        self, profile: AthleteProfile, goal: TrainingGoal, strategy: str
    ) -> dict[str, Any]: ...

    def readiness(
        self, profile: AthleteProfile, goal: TrainingGoal, plan: TrainingPlan | None
    ) -> RaceReadiness: ...


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
    # Kind of ``activity_intensity`` (running: pace_sec_per_km).
    intensity_kind: IntensityKind
    # Watch-workout target kinds the sport accepts.
    target_kinds: frozenset[TargetKind]
    # Typical speed, to estimate the duration of a distance-based workout step.
    default_speed_mps: float

    @property
    def race(self) -> RaceModel | None:
        """Race predictions / pacing / readiness, or None if the sport has none yet."""
        ...

    def format_intensity(self, intensity: Intensity) -> str:
        """Human-readable intensity, e.g. ``5:30/km``."""
        ...

    def activity_intensity(self, distance_m: float, duration_s: float) -> Intensity | None:
        """Average intensity of a recorded activity (running: pace), None if unknown."""
        ...

    # ── fitness and profile ──

    def build_profile(
        self, activities: list[ActivitySummary], platform_records: list[PersonalRecord]
    ) -> SportProfile:
        """The athlete's block for this sport, from its activities (onboarding)."""
        ...

    def fitness_from_race(self, distance_m: float, time_s: float) -> FitnessMarker:
        """Fitness marker from a race or time-trial result."""
        ...

    def describe_fitness(self, fitness: float) -> dict[str, Any]:
        """Tool payload for a fitness value: training targets, predictions…"""
        ...

    def training_zones(self, profile: AthleteProfile | None, fitness: float) -> dict[str, Any]:
        """Tool payload of the sport's training zones for *fitness*."""
        ...

    # ── plans and watch workouts ──

    def generate_plan(
        self,
        goal: TrainingGoal,
        profile: AthleteProfile,
        constraints: TrainingConstraints,
        start_date: date,
        lang: Language,
    ) -> TrainingPlan:
        """Periodized plan to *goal*. ValueError when the profile lacks data."""
        ...

    def carries_quality(self, workout: PlannedWorkout) -> bool:
        """True when the session is worth a structured watch workout."""
        ...

    def workout_to_dsl(self, workout: PlannedWorkout, profile: AthleteProfile | None) -> Conversion:
        """The watch workout for a plan session, or the reason it cannot be built."""
        ...

    def adapt_workout(
        self,
        recovery: RecoveryAssessment,
        workout: PlannedWorkout,
        profile: AthleteProfile | None,
    ) -> AdaptiveRecommendation:
        """Adjust today's planned session to the recovery status."""
        ...
