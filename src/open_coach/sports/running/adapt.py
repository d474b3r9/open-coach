"""Running session adjustments from the recovery status."""

from __future__ import annotations

from open_coach.models import (
    AdaptiveRecommendation,
    AthleteProfile,
    PlannedWorkout,
    RecoveryAssessment,
)
from open_coach.sports.running import vdot_of
from open_coach.sports.running.vdot import format_pace, training_paces


def adapt_running_workout(
    recovery: RecoveryAssessment,
    planned_workout: PlannedWorkout,
    profile: AthleteProfile | None = None,
) -> AdaptiveRecommendation:
    """Adjust a planned run to the recovery status (easy-pace substitutions from VDOT)."""
    wtype = planned_workout.workout_type
    desc = planned_workout.description or wtype
    original = desc

    # Get easy pace for substitution suggestions
    easy_pace_str = ""
    if vdot := vdot_of(profile):
        paces = training_paces(vdot)
        easy_fast, easy_slow = paces["easy"]
        easy_pace_str = f"{format_pace(easy_fast)}-{format_pace(easy_slow)}/km"

    # Green: always proceed
    if recovery.status == "green":
        return AdaptiveRecommendation(
            action="proceed",
            reasoning=(
                f"Recovery is good (score {recovery.overall_score:.0f}/100). Proceed with {desc}."
            ),
            original_workout=original,
        )

    # Red: swap or rest
    if recovery.status == "red":
        if wtype in ("long_run",):
            return AdaptiveRecommendation(
                action="rest_day",
                reasoning=(
                    f"Recovery is poor (score {recovery.overall_score:.0f}/100). "
                    f"A long run would add too much stress. Take a rest day."
                ),
                original_workout=original,
            )
        # Any other workout type: swap to easy
        adjusted = f"Easy 30min{f' at {easy_pace_str}' if easy_pace_str else ''}"
        return AdaptiveRecommendation(
            action="swap_to_easy",
            reasoning=(
                f"Recovery is poor (score {recovery.overall_score:.0f}/100). "
                f"Replace {wtype} session with an easy run."
            ),
            original_workout=original,
            adjusted_workout=adjusted,
        )

    # Yellow: depends on workout type
    if wtype in ("easy", "recovery"):
        return AdaptiveRecommendation(
            action="proceed",
            reasoning=(
                f"Recovery is moderate (score {recovery.overall_score:.0f}/100) "
                f"but an easy run is fine."
            ),
            original_workout=original,
        )

    if wtype in ("tempo", "intervals"):
        adjusted = f"Easy{f' at {easy_pace_str}' if easy_pace_str else ' run'}"
        if planned_workout.target_distance_m:
            adjusted += f" — {planned_workout.target_distance_m / 1000:.0f}km"
        return AdaptiveRecommendation(
            action="reduce_intensity",
            reasoning=(
                f"Recovery is moderate (score {recovery.overall_score:.0f}/100). "
                f"Drop intensity from {wtype} to easy pace."
            ),
            original_workout=original,
            adjusted_workout=adjusted,
            intensity_reduction_pct=0.20,
        )

    if wtype == "long_run":
        reduced_km = None
        planned_km = (planned_workout.target_distance_m or 0) / 1000
        if planned_km:
            reduced_km = round(planned_km * 0.8, 1)
        adjusted = "Long run"
        if reduced_km:
            adjusted += f" {reduced_km}km (reduced from {planned_km:.0f}km)"
        if easy_pace_str:
            adjusted += f" at {easy_pace_str}"
        return AdaptiveRecommendation(
            action="reduce_volume",
            reasoning=(
                f"Recovery is moderate (score {recovery.overall_score:.0f}/100). "
                f"Reduce long run distance by ~20%."
            ),
            original_workout=original,
            adjusted_workout=adjusted,
            intensity_reduction_pct=0.20,
        )

    # Unknown workout type: default to reduce intensity
    return AdaptiveRecommendation(
        action="reduce_intensity",
        reasoning=(
            f"Recovery is moderate (score {recovery.overall_score:.0f}/100). "
            f"Consider reducing the intensity of today's {wtype} session."
        ),
        original_workout=original,
        intensity_reduction_pct=0.20,
    )
