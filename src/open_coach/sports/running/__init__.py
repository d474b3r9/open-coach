"""Running plugin: Daniels VDOT, pace zones, periodized plans, race tools.

``RunningSport`` implements ``sports.base.Sport``; its methods delegate to the
modules of this package (imported lazily — they import this package back).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from open_coach.sports.base import (
    Conversion,
    FitnessMarker,
    Intensity,
    IntensityKind,
    RaceModel,
    SportKey,
    TargetKind,
)

# Session strings for plan descriptions and markdown labels.
from open_coach.sports.running import i18n as _i18n  # noqa: F401
from open_coach.sports.running.vdot import (
    HALF_MARATHON_M,
    MARATHON_M,
    calculate_vdot,
    format_pace,
    format_time,
    predict_time,
    training_paces,
)

if TYPE_CHECKING:
    from open_coach.models import (
        ActivitySummary,
        AdaptiveRecommendation,
        AthleteProfile,
        Language,
        PersonalRecord,
        PlannedWorkout,
        RecoveryAssessment,
        SportProfile,
        TrainingConstraints,
        TrainingGoal,
        TrainingPlan,
    )

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
    intensity_kind: IntensityKind = "pace_sec_per_km"
    target_kinds: frozenset[TargetKind] = frozenset({"pace", "heart_rate"})
    default_speed_mps = 1000 / 300  # 5:00/km

    @property
    def race(self) -> RaceModel | None:
        return _race_model()

    def format_intensity(self, intensity: Intensity) -> str:
        if intensity.kind == "pace_sec_per_km":
            # round() before formatting: format_pace itself truncates.
            return f"{format_pace(round(intensity.value))}/km"
        return f"{round(intensity.value)} bpm"

    def activity_intensity(self, distance_m: float, duration_s: float) -> Intensity | None:
        return pace(avg_pace_sec_per_km(duration_s, distance_m))

    # ── fitness and profile ──

    def build_profile(
        self, activities: list[ActivitySummary], platform_records: list[PersonalRecord]
    ) -> SportProfile:
        from open_coach.sports.running.profile import build_running_profile

        return build_running_profile(activities, platform_records)

    def fitness_from_race(self, distance_m: float, time_s: float) -> FitnessMarker:
        vdot = calculate_vdot(distance_m, time_s)
        source = f"{distance_m / 1000:g} km in {format_time(time_s)}"
        return FitnessMarker(metric=VDOT_METRIC, value=round(vdot, 1), source=source)

    def describe_fitness(self, fitness: float) -> dict[str, Any]:
        predictions = {
            name: format_time(predict_time(fitness, dist))
            for name, dist in [
                ("5K", 5000),
                ("10K", 10000),
                ("Half", HALF_MARATHON_M),
                ("Marathon", MARATHON_M),
            ]
        }
        paces = {
            zone: f"{format_pace(fast)} - {format_pace(slow)}/km"
            for zone, (fast, slow) in training_paces(fitness).items()
        }
        return {
            "vdot": round(fitness, 1),
            "training_paces": paces,
            "race_predictions": predictions,
        }

    def training_zones(self, profile: AthleteProfile | None, fitness: float) -> dict[str, Any]:
        from open_coach.sports.running.zones import zones_payload

        return zones_payload(profile, fitness)

    # ── plans and watch workouts ──

    def generate_plan(
        self,
        goal: TrainingGoal,
        profile: AthleteProfile,
        constraints: TrainingConstraints,
        start_date: date,
        lang: Language,
    ) -> TrainingPlan:
        from open_coach.sports.running.plan import generate_plan

        vdot = vdot_of(profile)
        if vdot is None:
            raise ValueError("No VDOT available. Run bootstrap_athlete_profile first.")
        pattern = profile.sport_profile(RUNNING).training_pattern
        current_km = (
            pattern.weekly_distance_m / 1000 if pattern else max(20.0, (profile.ctl or 30.0) * 0.9)
        )
        return generate_plan(goal, vdot, current_km, constraints, start_date, lang)

    def carries_quality(self, workout: PlannedWorkout) -> bool:
        from open_coach.sports.running.plan_to_dsl import carries_quality

        return carries_quality(workout)

    def workout_to_dsl(self, workout: PlannedWorkout, profile: AthleteProfile | None) -> Conversion:
        from open_coach.sports.running.plan_to_dsl import convert_planned_workout

        vdot = vdot_of(profile)
        return convert_planned_workout(workout, training_paces(vdot) if vdot else None)

    def adapt_workout(
        self,
        recovery: RecoveryAssessment,
        workout: PlannedWorkout,
        profile: AthleteProfile | None,
    ) -> AdaptiveRecommendation:
        from open_coach.sports.running.adapt import adapt_running_workout

        return adapt_running_workout(recovery, workout, profile)


def _race_model() -> RaceModel:
    from open_coach.sports.running.race import RunningRace

    return RunningRace()


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
