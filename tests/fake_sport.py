"""A minimal, heart-rate-only sport plugin used to prove the core is sport-agnostic.

It lives in the tests on purpose: registering it (``registry.register_sport``)
must be the only step needed for the core — models, storage, plan tools,
renderer, metrics — to handle a second sport. Duration-based volume and
heart-rate targets exercise the paths running does not take.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from open_coach.models import (
    AdaptiveRecommendation,
    PlannedWorkout,
    SportProfile,
    TrainingPlan,
    TrainingWeek,
)
from open_coach.periodization import assign_week_types, available_day_indices, volume_for_week
from open_coach.sports.base import (
    Conversion,
    FitnessMarker,
    Intensity,
    IntensityKind,
    RaceModel,
    TargetKind,
    Volume,
)
from open_coach.workout_dsl import (
    CooldownStep,
    DSLWorkout,
    Duration,
    HeartRateTarget,
    IntervalStep,
    RepeatBlock,
    WarmupStep,
)

if TYPE_CHECKING:
    from open_coach.models import (
        ActivitySummary,
        AthleteProfile,
        Language,
        PersonalRecord,
        RecoveryAssessment,
        TrainingConstraints,
        TrainingGoal,
    )

FAKE = "fakesport"


def _lthr(profile: AthleteProfile | None) -> float | None:
    sp = profile.sports.get(FAKE) if profile else None
    return sp.fitness.value if sp and sp.fitness else None


class FakeSport:
    key = FAKE
    fitness_metric = "lthr"
    volume_metric: Literal["distance", "duration"] = "duration"
    workout_types = frozenset({"steady", "threshold"})
    quality_types = frozenset({"threshold"})
    intensity_kind: IntensityKind = "heart_rate_bpm"
    target_kinds: frozenset[TargetKind] = frozenset({"heart_rate"})
    default_speed_mps = 5.0

    @property
    def race(self) -> RaceModel | None:
        return None

    def format_intensity(self, intensity: Intensity) -> str:
        return f"{round(intensity.value)} bpm"

    def activity_intensity(self, distance_m: float, duration_s: float) -> Intensity | None:
        return None  # no pace notion; heart rate comes from the activity itself

    def build_profile(
        self, activities: list[ActivitySummary], platform_records: list[PersonalRecord]
    ) -> SportProfile:
        hrs = [a.avg_hr for a in activities if a.avg_hr]
        fitness = FitnessMarker(metric="lthr", value=max(hrs)) if hrs else None
        return SportProfile(fitness=fitness, personal_records=platform_records)

    def fitness_from_race(self, distance_m: float, time_s: float) -> FitnessMarker:
        return FitnessMarker(metric="lthr", value=165, source="field test")

    def describe_fitness(self, fitness: float) -> dict[str, Any]:
        return {"lthr": fitness}

    def training_zones(self, profile: AthleteProfile | None, fitness: float) -> dict[str, Any]:
        return {"zones": {"z2": f"{round(fitness * 0.8)}-{round(fitness * 0.9)} bpm"}}

    def generate_plan(
        self,
        goal: TrainingGoal,
        profile: AthleteProfile,
        constraints: TrainingConstraints,
        start_date: date,
        lang: Language,
    ) -> TrainingPlan:
        lthr = _lthr(profile)
        if lthr is None:
            raise ValueError("No LTHR available.")
        assert goal.race_date is not None
        total = (goal.race_date - start_date).days // 7 + 1
        week_types = assign_week_types(total, taper=1, peak=1)
        days = available_day_indices(constraints) or [1, 3, 5]
        weeks = []
        for i, week_type in enumerate(week_types):
            week_start = start_date + timedelta(weeks=i)
            hours = volume_for_week(i, week_type, 4.0, 6.0, week_types)
            workouts = [
                PlannedWorkout(
                    date=week_start + timedelta(days=d),
                    workout_type="threshold" if n == 0 and week_type == "build" else "steady",
                    description="Threshold 3x10 min" if n == 0 else "Steady ride",
                    target_duration_s=hours * 3600 / len(days),
                    target_intensity=Intensity(kind="heart_rate_bpm", value=lthr * 0.85),
                )
                for n, d in enumerate(days)
            ]
            weeks.append(
                TrainingWeek(
                    week_number=i + 1,
                    start_date=week_start,
                    planned_volume={FAKE: Volume(duration_s=hours * 3600)},
                    workouts=workouts,
                    notes=week_type,
                )
            )
        return TrainingPlan(
            name=f"{goal.race_name} plan",
            goal=goal,
            start_date=start_date,
            end_date=goal.race_date,
            weeks=weeks,
            created_at=datetime.now(),
        )

    def carries_quality(self, workout: PlannedWorkout) -> bool:
        return workout.workout_type in self.quality_types

    def workout_to_dsl(self, workout: PlannedWorkout, profile: AthleteProfile | None) -> Conversion:
        lthr = _lthr(profile)
        if lthr is None or workout.workout_type != "threshold":
            return Conversion(None, "only threshold sessions are pushed")
        target = HeartRateTarget(min_bpm=round(lthr * 0.95), max_bpm=round(lthr))
        return Conversion(
            DSLWorkout(
                sport=FAKE,
                name=workout.description,
                steps=[
                    WarmupStep(duration=Duration(lap_button=True)),
                    RepeatBlock(
                        count=3, steps=[IntervalStep(duration=Duration(seconds=600), target=target)]
                    ),
                    CooldownStep(duration=Duration(lap_button=True)),
                ],
            )
        )

    def adapt_workout(
        self,
        recovery: RecoveryAssessment,
        workout: PlannedWorkout,
        profile: AthleteProfile | None,
    ) -> AdaptiveRecommendation:
        reasoning = f"fake sport: {recovery.status}"
        if recovery.status == "red":
            return AdaptiveRecommendation(action="rest_day", reasoning=reasoning)
        return AdaptiveRecommendation(action="proceed", reasoning=reasoning)
