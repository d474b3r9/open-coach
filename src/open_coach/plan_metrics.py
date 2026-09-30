"""Pure helpers to recompute per-week actuals of a training plan (no I/O)."""

from __future__ import annotations

from open_coach.models import PlannedWorkout, TrainingWeek
from open_coach.sports.base import NON_SPORT_WORKOUT_TYPES, SportKey, Volume


def is_sport_workout(workout: PlannedWorkout) -> bool:
    """True when the session counts toward completion (rest / strength excluded)."""
    return workout.workout_type.casefold() not in NON_SPORT_WORKOUT_TYPES


def recompute_week_actuals(week: TrainingWeek, default_sport: SportKey) -> None:
    """Refresh ``actual_volume`` and ``completion_rate`` in place.

    - actual_volume[sport] = distance / duration of completed sessions of that
      sport (a completed session with nothing recorded counts 0 — no guessing)
      + every ``extra_activities`` entry of that sport. A session without its own
      sport belongs to *default_sport* (the plan's).
    - completion_rate = completed sport sessions / sport sessions
      (workout types in NON_SPORT_WORKOUT_TYPES are excluded from both counts).
    """
    volume: dict[SportKey, Volume] = {}

    def add(sport: SportKey, distance_m: float | None, duration_s: float | None) -> None:
        v = volume.setdefault(sport, Volume())
        v.distance_m = round(v.distance_m + (distance_m or 0.0), 1)
        v.duration_s = round(v.duration_s + (duration_s or 0.0), 1)

    sessions = [w for w in week.workouts if is_sport_workout(w)]
    for w in sessions:
        if w.completed:
            add(w.sport or default_sport, w.actual_distance_m, w.actual_duration_s)
    for a in week.extra_activities:
        add(a.sport, a.distance_m, a.duration_s)
    week.actual_volume = volume

    done = sum(1 for w in sessions if w.completed)
    week.completion_rate = done / len(sessions) if sessions else 0.0
