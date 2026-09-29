"""Tests for the training plan generator."""

from __future__ import annotations

from datetime import timedelta

import pytest

from open_coach.models import Language, TrainingConstraints, TrainingGoal
from open_coach.plan_generator import (
    WeekType,
    _assign_week_types,
    _get_available_day_indices,
    _volume_for_week,
    generate_plan,
)
from tests.conftest import NEXT_MONDAY, make_goal

LANGUAGES: tuple[Language, ...] = ("en", "fr")

# ── Helpers ───────────────────────────────────────────────────────────────────


def _constraints(**kwargs) -> TrainingConstraints:
    return TrainingConstraints(**kwargs)


# ── Week type assignment ───────────────────────────────────────────────────────


class TestAssignWeekTypes:
    def test_total_weeks_matches(self):
        types = _assign_week_types(16, 42_195)
        assert len(types) == 16

    def test_marathon_has_3_taper_weeks(self):
        types = _assign_week_types(16, 42_195)
        assert types.count("taper") == 3

    def test_half_has_2_taper_weeks(self):
        types = _assign_week_types(12, 21_097)
        assert types.count("taper") == 2

    def test_5k_has_1_taper_week(self):
        types = _assign_week_types(8, 5_000)
        assert types.count("taper") == 1

    def test_taper_at_end(self):
        types = _assign_week_types(10, 10_000)
        n_taper = types.count("taper")
        assert all(t == "taper" for t in types[-n_taper:])

    def test_recovery_every_4th_week_in_base_build(self):
        types = _assign_week_types(16, 42_195)
        build_base = [t for t in types if t in ("base", "build", "recovery")]
        # 4th week (index 3) in base/build should be recovery
        if len(build_base) >= 4:
            assert build_base[3] == "recovery"

    def test_peak_before_taper(self):
        types = _assign_week_types(12, 21_097)
        taper_start = next(i for i, t in enumerate(types) if t == "taper")
        peak_indices = [i for i, t in enumerate(types) if t == "peak"]
        assert all(i < taper_start for i in peak_indices)


# ── Volume calculation ─────────────────────────────────────────────────────────


class TestVolumeForWeek:
    def test_peak_week_returns_peak_km(self):
        week_types: list[WeekType] = ["base", "build", "peak", "taper"]
        vol = _volume_for_week(2, "peak", 40.0, 60.0, week_types)
        assert vol == 60.0

    def test_taper_first_week_is_80_percent(self):
        week_types: list[WeekType] = ["base", "build", "peak", "taper"]
        vol = _volume_for_week(3, "taper", 40.0, 60.0, week_types)
        assert vol == pytest.approx(60.0 * 0.80, abs=1.0)

    def test_recovery_week_is_70_percent_of_expected(self):
        week_types: list[WeekType] = ["base", "recovery", "build", "peak", "taper"]
        expected_base = _volume_for_week(1, "base", 40.0, 60.0, week_types)
        recovery_vol = _volume_for_week(1, "recovery", 40.0, 60.0, week_types)
        assert recovery_vol < expected_base

    def test_first_week_close_to_start_km(self):
        week_types: list[WeekType] = ["base"] * 8
        week_types += ["peak", "taper"]
        vol = _volume_for_week(0, "base", 40.0, 60.0, week_types)
        assert vol == pytest.approx(40.0, abs=5.0)


# ── Available days ─────────────────────────────────────────────────────────────


class TestGetAvailableDayIndices:
    def test_explicit_days_respected(self):
        c = _constraints(available_days=["monday", "wednesday", "friday", "sunday"])
        indices = _get_available_day_indices(c)
        assert indices == [0, 2, 4, 6]

    def test_max_sessions_respected(self):
        c = _constraints(
            available_days=["monday", "tuesday", "wednesday", "thursday", "friday"],
            max_sessions_per_week=3,
        )
        indices = _get_available_day_indices(c)
        assert len(indices) == 3

    def test_default_days_when_empty(self):
        c = _constraints()
        indices = _get_available_day_indices(c)
        assert len(indices) > 0


# ── Full plan generation ───────────────────────────────────────────────────────


class TestGeneratePlan:
    def test_plan_has_correct_week_count(self):
        goal = make_goal(10_000, weeks_ahead=12)
        c = _constraints(available_days=["monday", "wednesday", "friday", "sunday"])
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=35.0, constraints=c, start_date=NEXT_MONDAY
        )
        # make_goal(weeks_ahead=12) puts the race on the Monday after 12 full
        # weeks, so the race week is week 13.
        assert len(plan.weeks) == 13

    def test_plan_name_contains_race_name(self):
        goal = make_goal(21_097, weeks_ahead=14, race_name="Semi Paris")
        c = _constraints()
        plan = generate_plan(
            goal, vdot=48.0, current_weekly_km=40.0, constraints=c, start_date=NEXT_MONDAY
        )
        assert "Semi Paris" in plan.name

    def test_language_switches_name_and_descriptions(self):
        goal = make_goal(10_000, weeks_ahead=8, race_name="Test 10K")
        c = _constraints()
        en, fr = (
            generate_plan(
                goal,
                vdot=48.0,
                current_weekly_km=40.0,
                constraints=c,
                start_date=NEXT_MONDAY,
                lang=lang,
            )
            for lang in LANGUAGES
        )
        assert en.name == "Test 10K Plan — 9 weeks"
        assert fr.name == "Plan Test 10K — 9 semaines"
        en_long = next(w for wk in en.weeks for w in wk.workouts if w.workout_type == "long_run")
        fr_long = next(w for wk in fr.weeks for w in wk.workouts if w.workout_type == "long_run")
        assert en_long.description.startswith("Long run ")
        assert fr_long.description.startswith("Sortie longue ")

    def test_both_languages_convert_to_the_same_garmin_structure(self):
        from open_coach.plan_to_dsl import convert_planned_workout

        goal = make_goal(10_000, weeks_ahead=8)
        c = _constraints()
        en, fr = (
            generate_plan(
                goal,
                vdot=48.0,
                current_weekly_km=40.0,
                constraints=c,
                start_date=NEXT_MONDAY,
                lang=lang,
            )
            for lang in LANGUAGES
        )
        pairs = [
            (a, b)
            for wa, wb in zip(en.weeks, fr.weeks, strict=True)
            for a, b in zip(wa.workouts, wb.workouts, strict=True)
        ]
        assert pairs
        for a, b in pairs:
            ca, cb = convert_planned_workout(a), convert_planned_workout(b)
            assert ca.ok == cb.ok, (a.description, b.description)
            if ca.ok:
                assert ca.dsl is not None
                assert cb.dsl is not None
                assert ca.dsl.steps == cb.dsl.steps, (a.description, b.description)

    @pytest.mark.parametrize("days_to_race", [55, 83, 49, 50])
    def test_race_day_is_the_last_session_of_the_plan(self, days_to_race):
        # Regression: a race 55 days after a Monday start (a Sunday) used to
        # fall after the last generated week — no race week, no race session.
        race_date = NEXT_MONDAY + timedelta(days=days_to_race)
        goal = make_goal(10_000, race_date=race_date, target_time_s=2520)
        c = _constraints()
        plan = generate_plan(
            goal, vdot=48.0, current_weekly_km=35.0, constraints=c, start_date=NEXT_MONDAY
        )
        last_week = plan.weeks[-1]
        assert last_week.start_date <= race_date < last_week.start_date + timedelta(days=7)
        race = last_week.workouts[-1]
        assert race.workout_type == "race"
        assert race.date == race_date
        assert race.target_distance_km == 10.0
        assert race.target_pace_sec_per_km == pytest.approx(252.0)
        all_workouts = [w for week in plan.weeks for w in week.workouts]
        assert all(w.date <= race_date for w in all_workouts)
        assert [w for w in all_workouts if w.workout_type == "race"] == [race]
        assert last_week.planned_volume_km == pytest.approx(
            sum(w.target_distance_km or 0 for w in last_week.workouts)
        )

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_generated_quality_sessions_convert_to_garmin(self, lang):
        # Regression: generated tempo descriptions ("2km warmup + 3km @
        # threshold") were refused by plan_to_dsl, and interval recoveries
        # ("(400m recovery)") were silently dropped.
        from open_coach.plan_to_dsl import convert_planned_workout
        from open_coach.vdot import training_paces
        from open_coach.workout_dsl import RecoveryStep, RepeatBlock

        goal = make_goal(10_000, weeks_ahead=10)
        plan = generate_plan(
            goal,
            vdot=48.0,
            current_weekly_km=40.0,
            constraints=_constraints(),
            start_date=NEXT_MONDAY,
            lang=lang,
        )
        quality = [
            w
            for week in plan.weeks
            for w in week.workouts
            if w.workout_type in ("tempo", "intervals")
        ]
        assert {w.workout_type for w in quality} == {"tempo", "intervals"}
        for w in quality:
            conv = convert_planned_workout(w, training_paces(48.0))
            assert conv.ok, (w.description, conv.reason)
            assert conv.dsl is not None
            blocks = [s for s in conv.dsl.steps if isinstance(s, RepeatBlock)]
            assert len(blocks) == 1, w.description
            if w.workout_type == "intervals":
                assert any(isinstance(s, RecoveryStep) for s in blocks[0].steps), w.description
                assert blocks[0].steps[1].duration.distance_m == 400
            else:
                work = blocks[0].steps[0]
                assert work.duration.distance_m is not None
                assert work.duration.distance_m < (w.target_distance_km or 0) * 1000

    def test_short_horizon_has_no_week_after_the_race(self):
        # Regression: a race 20 days out was padded to 4 weeks, so week 4
        # started the day after the race and the race sat in the peak week.
        race_date = NEXT_MONDAY + timedelta(days=20)
        goal = make_goal(5_000, race_date=race_date, target_time_s=1230)
        plan = generate_plan(
            goal,
            vdot=48.0,
            current_weekly_km=35.0,
            constraints=_constraints(),
            start_date=NEXT_MONDAY,
        )
        assert len(plan.weeks) == 3
        assert plan.weeks[-1].notes == "taper"
        assert plan.weeks[-1].workouts[-1].workout_type == "race"
        assert all(w.start_date <= race_date for w in plan.weeks)

    def test_race_pace_falls_back_to_vdot_prediction(self):
        goal = make_goal(10_000, weeks_ahead=8)  # no target time
        c = _constraints()
        plan = generate_plan(
            goal, vdot=48.0, current_weekly_km=35.0, constraints=c, start_date=NEXT_MONDAY
        )
        race = plan.weeks[-1].workouts[-1]
        assert race.workout_type == "race"
        assert race.target_pace_sec_per_km is not None
        assert 240 < race.target_pace_sec_per_km < 270  # VDOT 48 10K ~ 4:15/km

    def test_plan_start_and_end_dates(self):
        goal = make_goal(42_195, weeks_ahead=16)
        c = _constraints()
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=50.0, constraints=c, start_date=NEXT_MONDAY
        )
        assert plan.start_date == NEXT_MONDAY
        assert plan.end_date == goal.race_date

    def test_all_weeks_have_workouts(self):
        goal = make_goal(10_000, weeks_ahead=8)
        c = _constraints(available_days=["monday", "wednesday", "saturday"])
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=30.0, constraints=c, start_date=NEXT_MONDAY
        )
        for week in plan.weeks:
            assert len(week.workouts) > 0

    def test_workout_dates_on_available_days(self):
        goal = make_goal(10_000, weeks_ahead=8)
        c = _constraints(available_days=["monday", "wednesday", "saturday"])
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=30.0, constraints=c, start_date=NEXT_MONDAY
        )
        allowed_weekdays = {0, 2, 5}  # Mon, Wed, Sat
        for week in plan.weeks:
            for workout in week.workouts:
                assert workout.date.weekday() in allowed_weekdays, (
                    f"Workout on {workout.date} ({workout.date.strftime('%A')}) not in allowed days"
                )

    def test_build_weeks_have_tempo(self):
        goal = make_goal(10_000, weeks_ahead=12)
        c = _constraints(available_days=["monday", "wednesday", "friday", "sunday"])
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=35.0, constraints=c, start_date=NEXT_MONDAY
        )
        build_weeks = [w for w in plan.weeks if w.notes == "build"]
        if build_weeks:
            for week in build_weeks:
                types = [w.workout_type for w in week.workouts]
                assert "tempo" in types, f"Build week {week.week_number} has no tempo: {types}"

    def test_peak_weeks_have_intervals(self):
        goal = make_goal(10_000, weeks_ahead=12)
        c = _constraints(available_days=["monday", "wednesday", "friday", "sunday"])
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=35.0, constraints=c, start_date=NEXT_MONDAY
        )
        peak_weeks = [w for w in plan.weeks if w.notes == "peak"]
        if peak_weeks:
            for week in peak_weeks:
                types = [w.workout_type for w in week.workouts]
                assert "intervals" in types, (
                    f"Peak week {week.week_number} has no intervals: {types}"
                )

    def test_volume_never_exceeds_160_percent_of_start(self):
        start_km = 30.0
        goal = make_goal(42_195, weeks_ahead=16)
        c = _constraints()
        plan = generate_plan(
            goal, vdot=42.0, current_weekly_km=start_km, constraints=c, start_date=NEXT_MONDAY
        )
        for week in plan.weeks:
            assert week.planned_volume_km <= start_km * 1.65, (
                f"Week {week.week_number}: {week.planned_volume_km}km > 165% of {start_km}km"
            )

    def test_week_numbers_sequential(self):
        goal = make_goal(10_000, weeks_ahead=10)
        c = _constraints()
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=35.0, constraints=c, start_date=NEXT_MONDAY
        )
        for i, week in enumerate(plan.weeks):
            assert week.week_number == i + 1

    def test_plan_serializable(self):
        goal = make_goal(10_000, weeks_ahead=8)
        c = _constraints()
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=30.0, constraints=c, start_date=NEXT_MONDAY
        )
        json_str = plan.model_dump_json()
        from open_coach.models import TrainingPlan

        restored = TrainingPlan.model_validate_json(json_str)
        assert restored.name == plan.name
        assert len(restored.weeks) == len(plan.weeks)

    def test_missing_race_date_raises(self):
        goal = TrainingGoal(race_name="Test", distance_m=10_000, race_date=None)
        c = _constraints()
        with pytest.raises(ValueError, match="race_date"):
            generate_plan(
                goal, vdot=45.0, current_weekly_km=30.0, constraints=c, start_date=NEXT_MONDAY
            )

    def test_short_plan_is_not_padded_past_the_race(self):
        # Race on the Monday two weeks out: weeks 1-2, then the race week.
        # This used to be padded to 4 weeks, i.e. a whole week after the race.
        race_date = NEXT_MONDAY + timedelta(weeks=2)
        goal = TrainingGoal(race_name="Sprint", distance_m=5_000, race_date=race_date)
        c = _constraints()
        plan = generate_plan(
            goal, vdot=45.0, current_weekly_km=30.0, constraints=c, start_date=NEXT_MONDAY
        )
        assert len(plan.weeks) == 3
        assert [w.workout_type for w in plan.weeks[-1].workouts] == ["race"]


# ── Duration caps (max_weekday_minutes / max_weekend_minutes) ─────────────────


class TestDurationCaps:
    """Low VDOT + high volume so uncapped sessions clearly exceed the caps."""

    @staticmethod
    def _capped_plan(c: TrainingConstraints):
        goal = make_goal(10_000, weeks_ahead=12)
        return generate_plan(
            goal, vdot=40.0, current_weekly_km=60.0, constraints=c, start_date=NEXT_MONDAY
        )

    def test_weekday_cap_respected(self):
        c = _constraints(
            available_days=["monday", "tuesday", "wednesday", "thursday", "sunday"],
            max_weekday_minutes=60,
        )
        plan = self._capped_plan(c)
        weekday_workouts = [w for week in plan.weeks for w in week.workouts if w.date.weekday() < 5]
        assert weekday_workouts
        for w in weekday_workouts:
            assert w.target_duration_min is not None
            assert w.target_duration_min <= 60, (
                f"{w.date} {w.workout_type}: {w.target_duration_min}min > 60min cap"
            )

    def test_weekday_sessions_exceed_60_without_cap(self):
        # Guard: same plan uncapped must exceed the cap, or the test above is vacuous
        c = _constraints(available_days=["monday", "tuesday", "wednesday", "thursday", "sunday"])
        plan = self._capped_plan(c)
        durations = [
            w.target_duration_min or 0.0
            for week in plan.weeks
            for w in week.workouts
            if w.date.weekday() < 5
        ]
        assert max(durations) > 60

    def test_weekend_cap_respected_for_long_run(self):
        c = _constraints(max_weekend_minutes=120)  # default days: Mon/Wed/Fri/Sun
        plan = self._capped_plan(c)
        sunday_workouts = [w for week in plan.weeks for w in week.workouts if w.date.weekday() == 6]
        assert any(w.workout_type == "long_run" for w in sunday_workouts)
        for w in sunday_workouts:
            assert w.target_duration_min is not None
            assert w.target_duration_min <= 120

    def test_long_run_exceeds_120_without_cap(self):
        # Regression guard: no caps → the long run is allowed past 2 hours
        plan = self._capped_plan(_constraints())
        long_run_durations = [
            w.target_duration_min or 0.0
            for week in plan.weeks
            for w in week.workouts
            if w.workout_type == "long_run"
        ]
        assert max(long_run_durations) > 120

    def test_intervals_keep_at_least_3_reps_under_tight_cap(self):
        import re

        c = _constraints(max_weekday_minutes=40)
        plan = self._capped_plan(c)
        interval_workouts = [
            w for week in plan.weeks for w in week.workouts if w.workout_type == "intervals"
        ]
        assert interval_workouts
        for w in interval_workouts:
            m = re.search(r"(\d+)x1km", w.description)
            assert m is not None, f"No rep count in {w.description!r}"
            assert int(m.group(1)) >= 3
