"""Pure helpers to recompute per-week actuals of a training plan (no I/O)."""

from __future__ import annotations

from open_coach.models import PlannedWorkout, TrainingWeek

# Session types that carry no running volume and are excluded from completion rate.
# "strength" is canonical; "kine-renfo" / "kiné-renfo" are the legacy French
# names still found in existing plans.
NON_RUN_TYPES = frozenset({"rest", "strength", "kine-renfo", "kiné-renfo"})  # fr-ok


def is_run_workout(workout: PlannedWorkout) -> bool:
    """True when the session counts toward completion (rest / strength excluded)."""
    return workout.workout_type.casefold() not in NON_RUN_TYPES


def recompute_week_actuals(week: TrainingWeek) -> None:
    """Refresh ``actual_volume_km`` and ``completion_rate`` in place.

    - actual_volume_km = sum of ``actual_distance_km`` over completed workouts
      (a completed workout with no recorded distance counts 0 — no guessing)
      + km of every ``extra_activities`` entry.
    - completion_rate = completed run sessions / run sessions
      (workout types in NON_RUN_TYPES are excluded from both counts).
    """
    planned_km = sum(w.actual_distance_km or 0.0 for w in week.workouts if w.completed)
    extra_km = sum(a.distance_km for a in week.extra_activities)
    week.actual_volume_km = round(planned_km + extra_km, 2)

    runs = [w for w in week.workouts if is_run_workout(w)]
    done = sum(1 for w in runs if w.completed)
    week.completion_rate = done / len(runs) if runs else 0.0
