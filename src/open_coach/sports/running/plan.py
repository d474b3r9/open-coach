"""Training plan generator: builds periodized plans from VDOT + constraints.

Pure computation — no I/O. Entry point: generate_plan().
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from open_coach.i18n import DEFAULT_LANGUAGE, t
from open_coach.models import (
    Language,
    PlannedWorkout,
    TrainingConstraints,
    TrainingGoal,
    TrainingPlan,
    TrainingWeek,
)
from open_coach.periodization import (
    WeekType,
    assign_week_types,
    available_day_indices,
    max_minutes_for_day,
    volume_for_week,
)
from open_coach.sports.base import Volume
from open_coach.sports.running import pace
from open_coach.sports.running.vdot import format_pace, predict_time, training_paces

# ── Distance-specific parameters ───────────────────────────────────────────────


def _taper_weeks(distance_m: float) -> int:
    if distance_m >= 40_000:
        return 3
    if distance_m >= 20_000:
        return 2
    return 1


def _peak_weeks(distance_m: float) -> int:
    return 2 if distance_m >= 20_000 else 1


def _target_peak_km(vdot: float, distance_m: float) -> float:
    """Typical peak weekly volume based on race distance and VDOT."""
    if distance_m >= 40_000:
        return min(80.0, max(50.0, vdot * 1.2))
    if distance_m >= 20_000:
        return min(65.0, max(40.0, vdot * 0.9))
    if distance_m >= 10_000:
        return min(55.0, max(30.0, vdot * 0.75))
    return min(45.0, max(25.0, vdot * 0.6))


# ── Day assignment ─────────────────────────────────────────────────────────────


# A day capped below this is too short for a long run or a quality session:
# it gets an easy run, unless no other day is available.
SHORT_DAY_MINUTES = 60


def _assign_roles(
    days: list[int], week_type: WeekType, caps: dict[int, int | None] | None = None
) -> dict[int, str]:
    """Map weekday index → workout role for one week.

    *caps* (weekday index → minutes) keeps the long run and the quality session
    off short days (under ``SHORT_DAY_MINUTES``) whenever a longer day exists.
    """
    if not days:
        return {}

    caps = caps or {}
    roomy = [d for d in days if (caps.get(d) or SHORT_DAY_MINUTES) >= SHORT_DAY_MINUTES]
    roles: dict[int, str] = {}

    # Long run: last available day that is long enough
    long_day = (roomy or days)[-1]
    roles[long_day] = "long_run"

    remaining = [d for d in days if d != long_day]

    # Quality session on build/peak weeks
    if week_type in ("build", "peak") and remaining:
        preferred = [d for d in remaining if d in roomy] or remaining
        # Prefer a day not immediately before the long run
        candidates = [d for d in preferred if d != long_day - 1] or preferred
        quality_day = candidates[len(candidates) // 2]
        roles[quality_day] = "tempo" if week_type == "build" else "intervals"

    # Fill remaining days
    for d in days:
        if d not in roles:
            roles[d] = "recovery_jog" if week_type == "recovery" else "easy"

    return roles


# ── Workout construction ───────────────────────────────────────────────────────


def _fmt_pace(sec_per_km: float) -> str:
    return f"{format_pace(sec_per_km)}/km"


def _cap_steady_run(
    dist: float, floor_km: float, pace: float, max_minutes: int | None
) -> tuple[float, float]:
    """Clamp a steady run to a duration cap, never below the distance floor."""
    dur = round(dist * pace / 60, 0)
    if max_minutes is not None and dur > max_minutes:
        dist = max(floor_km, round(max_minutes * 60 / pace, 1))
        dur = round(dist * pace / 60, 0)
    return dist, dur


def _targets(km: float, minutes: float, pace_sec_per_km: float) -> dict[str, Any]:
    """PlannedWorkout target fields from a distance in km, minutes and a pace."""
    return {
        "target_distance_m": round(km * 1000, 1),
        "target_duration_s": minutes * 60,
        "target_intensity": pace(pace_sec_per_km),
    }


def _make_workout(
    workout_date: date,
    role: str,
    weekly_km: float,
    n_sessions: int,
    paces: dict[str, tuple[float, float]],
    max_minutes: int | None = None,
    lang: Language = DEFAULT_LANGUAGE,
) -> PlannedWorkout:
    """Build a PlannedWorkout for a given role, honoring an optional duration cap."""
    session_km = weekly_km / n_sessions if n_sessions > 0 else 5.0

    easy_pace = paces["easy"][1]  # slower (upper) bound of easy zone
    thresh_pace = (paces["threshold"][0] + paces["threshold"][1]) / 2
    interval_pace = (paces["interval"][0] + paces["interval"][1]) / 2

    if role == "long_run":
        dist = round(min(32.0, session_km * 1.5), 1)
        dist, dur = _cap_steady_run(dist, 3.0, easy_pace, max_minutes)
        return PlannedWorkout(
            date=workout_date,
            workout_type="long_run",
            description=t("wo.long_run", lang, km=dist, pace=_fmt_pace(easy_pace)),
            **_targets(dist, dur, easy_pace),
        )

    if role == "easy":
        dist = round(max(4.0, session_km * 0.9), 1)
        dist, dur = _cap_steady_run(dist, 4.0, easy_pace, max_minutes)
        return PlannedWorkout(
            date=workout_date,
            workout_type="easy",
            description=t("wo.easy", lang, km=dist, pace=_fmt_pace(easy_pace)),
            **_targets(dist, dur, easy_pace),
        )

    if role == "recovery_jog":
        dist = round(max(3.0, session_km * 0.6), 1)
        dist, dur = _cap_steady_run(dist, 3.0, easy_pace, max_minutes)
        return PlannedWorkout(
            date=workout_date,
            workout_type="recovery",
            description=t("wo.recovery", lang, km=dist),
            **_targets(dist, dur, easy_pace),
        )

    if role == "tempo":
        warmup_km = 2.0
        cooldown_km = 1.5
        tempo_km = round(max(2.0, min(8.0, session_km * 0.5)), 1)
        if max_minutes is not None:
            shell_min = (warmup_km + cooldown_km) * easy_pace / 60
            budget_km = (max_minutes - shell_min) * 60 / thresh_pace
            tempo_km = round(max(2.0, min(tempo_km, budget_km)), 1)
        dist = round(warmup_km + tempo_km + cooldown_km, 1)
        dur = round(
            warmup_km * easy_pace / 60 + tempo_km * thresh_pace / 60 + cooldown_km * easy_pace / 60,
            0,
        )
        return PlannedWorkout(
            date=workout_date,
            workout_type="tempo",
            description=t("wo.tempo", lang, total=dist, km=tempo_km, pace=_fmt_pace(thresh_pace)),
            **_targets(dist, dur, thresh_pace),
        )

    if role == "intervals":
        n_reps = 4 if session_km < 8 else (5 if session_km < 12 else 6)
        warmup_km = 2.0
        cooldown_km = 1.5
        recovery_km = 0.4

        def _interval_duration(reps: int) -> float:
            return round(
                warmup_km * easy_pace / 60
                + reps * (interval_pace / 60 + recovery_km * easy_pace / 60)
                + cooldown_km * easy_pace / 60,
                0,
            )

        dur = _interval_duration(n_reps)
        if max_minutes is not None:
            while dur > max_minutes and n_reps > 3:
                n_reps -= 1
                dur = _interval_duration(n_reps)
        dist = round(warmup_km + n_reps * (1.0 + recovery_km) + cooldown_km, 1)
        return PlannedWorkout(
            date=workout_date,
            workout_type="intervals",
            description=t("wo.intervals", lang, reps=n_reps, pace=_fmt_pace(interval_pace)),
            **_targets(dist, dur, interval_pace),
        )

    # Fallback
    dist = round(max(3.0, session_km * 0.7), 1)
    dist, dur = _cap_steady_run(dist, 3.0, easy_pace, max_minutes)
    return PlannedWorkout(
        date=workout_date,
        workout_type="easy",
        description=t("wo.fallback", lang, km=dist),
        **_targets(dist, dur, easy_pace),
    )


def _race_week_workouts(
    workouts: list[PlannedWorkout],
    goal: TrainingGoal,
    vdot: float,
    lang: Language,
) -> list[PlannedWorkout]:
    """Drop sessions on or after race day and put the race itself on race day."""
    assert goal.race_date is not None
    race_km = goal.distance_m / 1000
    race_time_s = goal.target_time_s or predict_time(vdot, goal.distance_m)
    race_pace = race_time_s / race_km
    race = PlannedWorkout(
        date=goal.race_date,
        workout_type="race",
        description=t(
            "wo.race",
            lang,
            race=goal.race_name or f"{race_km:.0f}km",
            km=race_km,
            pace=_fmt_pace(race_pace),
        ),
        **_targets(round(race_km, 1), round(race_time_s / 60, 0), race_pace),
    )
    return [w for w in workouts if w.date < goal.race_date] + [race]


# ── Main entry point ──────────────────────────────────────────────────────────


def generate_plan(
    goal: TrainingGoal,
    vdot: float,
    current_weekly_km: float,
    constraints: TrainingConstraints,
    start_date: date,
    lang: Language = DEFAULT_LANGUAGE,
) -> TrainingPlan:
    """Generate a periodized training plan from athlete data.

    Args:
        goal: Target race (must have race_date).
        vdot: Current VDOT.
        current_weekly_km: Observed weekly training volume in km.
        constraints: Training constraints (days, sessions, time limits).
        start_date: First day of the plan. Should be a Monday for correct
                    day-of-week placement.
        lang: Language of the generated plan name and session descriptions.

    Returns:
        A complete TrainingPlan with weeks and workouts.
    """
    if goal.race_date is None:
        raise ValueError("goal.race_date is required to generate a plan")

    # +1 so the week containing race day is part of the plan (a race 55 days
    # after the start falls in week 8, not after week 7). No minimum: padding a
    # short horizon to 4 weeks scheduled whole weeks after the race.
    total_weeks = min(24, (goal.race_date - start_date).days // 7 + 1)

    # Peak volume: target for the race distance, capped at +60% of current
    peak_km = max(
        current_weekly_km,
        min(
            _target_peak_km(vdot, goal.distance_m),
            current_weekly_km * 1.6,
        ),
    )

    week_types = assign_week_types(
        total_weeks, _taper_weeks(goal.distance_m), _peak_weeks(goal.distance_m)
    )
    paces = training_paces(vdot)
    day_indices = available_day_indices(constraints) or [0, 2, 4, 6]

    weeks: list[TrainingWeek] = []

    for i, week_type in enumerate(week_types):
        week_start = start_date + timedelta(weeks=i)
        target_km = volume_for_week(i, week_type, current_weekly_km, peak_km, week_types)

        caps = {d: max_minutes_for_day(d, constraints) for d in day_indices}
        roles = _assign_roles(day_indices, week_type, caps)
        n_sessions = len(roles)

        workouts: list[PlannedWorkout] = []
        for day_idx, role in sorted(roles.items()):
            # Offset from week_start (assumed Monday, weekday=0)
            days_offset = (day_idx - week_start.weekday()) % 7
            workout_date = week_start + timedelta(days=days_offset)
            workouts.append(
                _make_workout(
                    workout_date,
                    role,
                    target_km,
                    n_sessions,
                    paces,
                    max_minutes=max_minutes_for_day(day_idx, constraints),
                    lang=lang,
                )
            )

        if week_start <= goal.race_date < week_start + timedelta(days=7):
            workouts = _race_week_workouts(workouts, goal, vdot, lang)
            target_km = round(sum(w.target_distance_m or 0.0 for w in workouts) / 1000, 1)

        weeks.append(
            TrainingWeek(
                week_number=i + 1,
                start_date=week_start,
                planned_volume={goal.sport: Volume(distance_m=round(target_km * 1000, 1))},
                workouts=workouts,
                notes=week_type,
            )
        )

    race_label = goal.race_name or f"{goal.distance_m / 1000:.0f}km"
    return TrainingPlan(
        name=t("plan.name", lang, race=race_label, weeks=total_weeks),
        goal=goal,
        start_date=start_date,
        end_date=goal.race_date,
        weeks=weeks,
        created_at=datetime.now(),
    )
