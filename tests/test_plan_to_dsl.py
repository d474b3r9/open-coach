"""Tests for plan_to_dsl — PlannedWorkout description → DSLWorkout.

The fixtures below are the *actual* descriptions written in the 2026 marathon
plan. Regression anchor: the 2026-09-10 session "10 km dont 15 min @ M 4:37"
was pushed as one 7.5 km block at M pace by the old heuristic.
"""

from __future__ import annotations

from datetime import date

import pytest

from open_coach.models import PlannedWorkout
from open_coach.plan_to_dsl import convert_planned_workout
from open_coach.sports.running import pace as running_pace
from open_coach.workout_dsl import (
    CooldownStep,
    IntervalStep,
    PaceTarget,
    RecoveryStep,
    RepeatBlock,
    WarmupStep,
)

# VDOT ~48.7 table, only the shape matters (fast, slow) sec/km
PACES = {
    "easy": (330.0, 350.0),
    "marathon": (275.0, 279.0),
    "threshold": (256.0, 260.0),
    "interval": (235.0, 245.0),
    "repetition": (216.0, 233.0),
}


def _w(wtype: str, description: str, dist: float | None = 10.0, pace: float | None = 330.0):
    return PlannedWorkout(
        date=date(2026, 9, 10),
        workout_type=wtype,
        description=description,
        target_distance_m=dist * 1000 if dist is not None else None,
        target_intensity=running_pace(pace),
    )


def _repeats(dsl) -> list[RepeatBlock]:
    return [s for s in dsl.steps if isinstance(s, RepeatBlock)]


def _window(step) -> tuple[int, int]:
    """(fast, slow) pace window of a step — asserts a pace target exists."""
    assert isinstance(step, IntervalStep)
    assert isinstance(step.target, PaceTarget)
    return (int(step.target.min_sec_per_km), int(step.target.max_sec_per_km))


def _assert_lap_wrapped(dsl) -> None:
    assert isinstance(dsl.steps[0], WarmupStep)
    assert dsl.steps[0].duration.lap_button
    assert isinstance(dsl.steps[-1], CooldownStep)
    assert dsl.steps[-1].duration.lap_button


# ── Regression: the 2026-09-10 session ───────────────────────────────────────


class TestEmbeddedMPaceBlock:
    def test_dont_15_min_at_m_is_a_15_min_block_not_the_whole_run(self):
        w = _w("tempo", "Q2 M-pace court : 10 km dont 15 min @ M 4:37 en milieu", 10.0, 277.0)
        conv = convert_planned_workout(w, PACES)
        assert conv.ok, conv.reason
        dsl = conv.dsl
        _assert_lap_wrapped(dsl)
        (block,) = _repeats(dsl)
        assert block.count == 1
        step = block.steps[0]
        assert isinstance(step, IntervalStep)
        assert step.duration.seconds == 15 * 60
        assert step.duration.distance_m is None
        assert _window(step) == (277 - 5, 277 + 5)

    def test_dont_30_min_at_m_letter_only_uses_vdot_table(self):
        w = _w("tempo", "Q2 M-pace : 12 km dont 30 min @ M", 12.0, 277.0)
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        step = _repeats(dsl)[0].steps[0]
        assert step.duration.seconds == 30 * 60
        assert _window(step) == (270, 284)

    def test_long_run_with_embedded_m_block_never_uses_easy_pace(self):
        # target pace on a long run is the EASY pace — must not leak into the M block
        w = _w("long_run", "SL 22 km dont 6 km @ M 4:37 en fin — gut 60-70 g/h", 22.0, 330.0)
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        _assert_lap_wrapped(dsl)
        step = _repeats(dsl)[0].steps[0]
        assert step.duration.distance_m == 6000
        assert _window(step)[1] == 277 + 5

    def test_long_run_embedded_letter_without_table_is_refused(self):
        w = _w("long_run", "SL 26 km dont 10 km @ M au milieu — gut 70-80 g/h", 26.0, 330.0)
        conv = convert_planned_workout(w, paces=None)
        assert not conv.ok
        assert "pace" in (conv.reason or "")


class TestEnglishEmbeddedBlock:
    @pytest.mark.parametrize("keyword", ["incl.", "incl", "including"])
    def test_english_keyword_matches_french_dont(self, keyword):
        fr = convert_planned_workout(_w("tempo", "10 km dont 15 min @ M 4:37", 10.0, 277.0), PACES)
        en = convert_planned_workout(
            _w("tempo", f"10 km {keyword} 15 min @ M 4:37", 10.0, 277.0), PACES
        )
        assert en.ok, en.reason
        assert fr.dsl is not None
        assert en.dsl is not None
        assert en.dsl.steps == fr.dsl.steps

    def test_english_long_run_with_m_block(self):
        w = _w("long_run", "LR 22 km including 6 km @ M 4:37 at the end", 22.0, 330.0)
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        _assert_lap_wrapped(dsl)
        assert _repeats(dsl)[0].steps[0].duration.distance_m == 6000

    def test_with_is_not_an_embedded_keyword(self):
        # "with 2 km warmup" must not become a 2 km block at tempo pace
        conv = convert_planned_workout(_w("tempo", "Tempo with 2 km warmup", 10.0, 256.0))
        assert not conv.ok


# ── Sets ─────────────────────────────────────────────────────────────────────


class TestSets:
    def test_threshold_km_reps_with_numeric_pace_and_minute_recovery(self):
        w = _w("tempo", "Q2 Tempo 3×3 km @ 4:45 r 2' jog — wu 15' lap, cd 10'", 12.0, 285.0)
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        _assert_lap_wrapped(dsl)
        (block,) = _repeats(dsl)
        assert block.count == 3
        work, rec = block.steps
        assert work.duration.distance_m == 3000
        assert _window(work) == (280, 290)
        assert isinstance(rec, RecoveryStep)
        assert rec.duration.seconds == 120
        assert rec.target is None

    def test_two_sets_each_with_own_pace_and_recovery(self):
        w = _w(
            "interval",
            "Q1 Amorce VO2 (T-2) : 3×1 km @ T 4:16-4:20 r 2' + 8×400 m @ I 3:58-4:05 r 200 m jog",
            12.0,
            258.0,
        )
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        b1, b2 = _repeats(dsl)
        assert (b1.count, b1.steps[0].duration.distance_m) == (3, 1000)
        assert _window(b1.steps[0]) == (251, 265)
        assert b1.steps[1].duration.seconds == 120
        assert (b2.count, b2.steps[0].duration.distance_m) == (8, 400)
        assert _window(b2.steps[0]) == (233, 250)
        assert b2.steps[1].duration.distance_m == 200

    def test_recovery_formats(self):
        cases = {
            "r 2'30 jog": 150,
            "r 90 s": 90,
            "r 2'": 120,
            "rec 2'": 120,
            "recovery 90 s": 90,
        }
        for rec_text, expected in cases.items():
            w = _w("interval", f"6×1 km @ I 3:55-4:02 {rec_text}", 12.0, 240.0)
            dsl = convert_planned_workout(w, PACES).dsl
            assert dsl is not None, rec_text
            assert _repeats(dsl)[0].steps[1].duration.seconds == expected, rec_text

    def test_pace_in_parentheses_after_seconds_per_rep(self):
        w = _w(
            "interval",
            "Piste : wu 15' lap + 8×200 m 42-45 s (3:30-3:45/km) r 200 m trot",
            8.0,
            None,
        )
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        block = _repeats(dsl)[0]
        assert block.count == 8
        assert _window(block.steps[0]) == (
            205,
            230,
        )

    def test_race_pace_label_before_numeric_pace(self):
        w = _w(
            "interval",
            "Opener J-5 : 2 km wu + 5×400 m @ 10K 4:12 r 200 m jog + 2 km cd",
            8.0,
            253.0,
        )
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        block = _repeats(dsl)[0]
        assert block.count == 5
        assert _window(block.steps[0]) == (
            247,
            257,
        )

    def test_ascii_x_and_meters(self):
        w = _w("intervals", "6x1000m @ interval pace", 10.0, 240.0)
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        block = _repeats(dsl)[0]
        assert (block.count, block.steps[0].duration.distance_m) == (6, 1000)
        # single set, no numeric pace, no zone letter → plan target pace ±5
        assert _window(block.steps[0]) == (
            235,
            245,
        )


# ── Steady runs (Rule A) ─────────────────────────────────────────────────────


class TestSteady:
    @pytest.mark.parametrize("wtype", ["easy", "long_run", "recovery"])
    def test_single_block_full_distance_easy_window(self, wtype):
        w = _w(wtype, "Footing 8 km easy 5:30-5:50 FC<145", 8.0, 330.0)
        dsl = convert_planned_workout(w, PACES).dsl
        assert dsl is not None
        assert len(dsl.steps) == 1  # no warmup, no cooldown (builder adds the lap finish)
        (block,) = _repeats(dsl)
        assert block.count == 1
        step = block.steps[0]
        assert step.duration.distance_m == 8000
        assert _window(step) == (325, 355)

    def test_steady_without_pace_is_refused(self):
        assert not convert_planned_workout(_w("easy", "footing", 8.0, None)).ok


# ── Refusals: never invent structure ─────────────────────────────────────────


class TestRefusals:
    def test_quality_without_structure_is_refused_not_guessed(self):
        conv = convert_planned_workout(_w("tempo", "VMA session", 10.0, 240.0))
        assert not conv.ok
        assert "structure" in (conv.reason or "")

    @pytest.mark.parametrize("wtype", ["race", "rest", "strength", "kine-renfo", "cross_training"])
    def test_non_pushable_types(self, wtype):
        conv = convert_planned_workout(_w(wtype, "whatever", 10.0, 250.0))
        assert not conv.ok
        assert wtype in (conv.reason or "")

    def test_race_like_times_are_not_mistaken_for_paces(self):
        # "41:30-42:45" must not parse as a pace; no set → refused anyway
        conv = convert_planned_workout(
            _w("tempo", "TEST 10K TT boucle plate (cible 41:30-42:45) + wu/cd 5 km", 15.0, 253.0)
        )
        assert not conv.ok


class TestCarriesQuality:
    @pytest.mark.parametrize(
        ("wtype", "description", "expected"),
        [
            ("easy", "Easy run 8 km", False),
            ("recovery", "Recovery jog 5 km", False),
            ("long_run", "LR 18 km easy", False),
            ("long_run", "SL 22 km dont 6 km @ M", True),
            ("long_run", "LR 22 km incl. 6 km @ M", True),
            ("tempo", "whatever", True),
            ("interval", "6×1 km @ I", True),
            ("race", "10K", True),
            ("rest", "", False),
            ("strength", "", False),
        ],
    )
    def test_carries_quality(self, wtype, description, expected):
        from open_coach.plan_to_dsl import carries_quality

        assert carries_quality(_w(wtype, description)) is expected
