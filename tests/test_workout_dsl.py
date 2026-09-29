"""Tests for workout_dsl — DSL models and text parser."""

from __future__ import annotations

import pytest

from open_coach.workout_dsl import (
    CooldownStep,
    DSLWorkout,
    Duration,
    IntervalStep,
    PaceTarget,
    RecoveryStep,
    RepeatBlock,
    WarmupStep,
    parse_dsl,
)

# ── Duration ──────────────────────────────────────────────────────────────────


class TestDuration:
    def test_seconds(self):
        d = Duration(seconds=600)
        assert d.estimated_seconds == 600

    def test_distance(self):
        d = Duration(distance_m=5000)
        assert d.estimated_seconds == pytest.approx(1500, rel=0.01)  # 5km @ 5:00/km

    def test_lap_button(self):
        d = Duration(lap_button=True)
        assert d.estimated_seconds == 600  # default 10 min

    def test_exactly_one_required(self):
        with pytest.raises(ValueError, match="exactly one of"):
            Duration(seconds=60, distance_m=1000)

    def test_none_raises(self):
        with pytest.raises(ValueError, match="exactly one of"):
            Duration()


# ── PaceTarget ────────────────────────────────────────────────────────────────


class TestPaceTarget:
    def test_valid(self):
        p = PaceTarget(min_sec_per_km=250, max_sec_per_km=265)
        assert p.min_sec_per_km == 250

    def test_faster_must_be_less_than_slower(self):
        with pytest.raises(ValueError, match="must be < max_sec_per_km"):
            PaceTarget(min_sec_per_km=265, max_sec_per_km=250)

    def test_to_speed_ms(self):
        p = PaceTarget(min_sec_per_km=250, max_sec_per_km=265)
        slow, fast = p.to_speed_ms()
        assert slow == pytest.approx(1000 / 265, rel=1e-3)
        assert fast == pytest.approx(1000 / 250, rel=1e-3)
        assert slow < fast  # slower pace → lower speed


# ── DSLWorkout validation ─────────────────────────────────────────────────────


class TestDSLWorkout:
    def _make_workout(self, n_repeats=5):
        return DSLWorkout(
            name="Test",
            steps=[
                WarmupStep(duration=Duration(seconds=600)),
                RepeatBlock(
                    count=n_repeats,
                    steps=[
                        IntervalStep(
                            duration=Duration(seconds=60),
                            pace=PaceTarget(min_sec_per_km=250, max_sec_per_km=265),
                        ),
                        RecoveryStep(duration=Duration(seconds=60)),
                    ],
                ),
                CooldownStep(duration=Duration(seconds=600)),
            ],
        )

    def test_valid(self):
        w = self._make_workout()
        assert w.name == "Test"
        assert len(w.steps) == 3

    def test_estimated_duration(self):
        w = self._make_workout(n_repeats=10)
        # warmup 600 + 10*(60+60) + cooldown 600 = 2400
        assert w.estimated_duration_s == 2400

    def test_step_count_limit(self):
        # warmup(1) + repeat_group(1) + 48 inner steps + cooldown(1) = 51 → exceeds 50
        inner: list[IntervalStep | RecoveryStep] = [
            IntervalStep(duration=Duration(seconds=60)) for _ in range(48)
        ]
        with pytest.raises(ValueError, match="50"):
            DSLWorkout(
                name="Too many",
                steps=[
                    WarmupStep(duration=Duration(seconds=300)),
                    RepeatBlock(count=1, steps=inner),
                    CooldownStep(duration=Duration(seconds=300)),
                ],
            )

    def test_empty_repeat_raises(self):
        with pytest.raises(ValueError, match="at least one step"):
            RepeatBlock(count=10, steps=[])


# ── Text parser ───────────────────────────────────────────────────────────────


class TestParseDsl:
    def test_basic(self):
        text = """
WARMUP: 10min
REPEAT: 10
  INTERVAL: 1min @ 4:10-4:25/km
  RECOVERY: 90s @ no_target
COOLDOWN: 10min
"""
        w = parse_dsl("10x1min", text)
        assert w.name == "10x1min"
        assert isinstance(w.steps[0], WarmupStep)
        assert w.steps[0].duration.seconds == 600

        repeat = w.steps[1]
        assert isinstance(repeat, RepeatBlock)
        assert repeat.count == 10

        interval = repeat.steps[0]
        assert isinstance(interval, IntervalStep)
        assert interval.duration.seconds == 60
        assert interval.pace is not None
        assert interval.pace.min_sec_per_km == 250  # 4:10
        assert interval.pace.max_sec_per_km == 265  # 4:25

        recovery = repeat.steps[1]
        assert isinstance(recovery, RecoveryStep)
        assert recovery.duration.seconds == 90
        assert recovery.pace is None  # no_target

        assert isinstance(w.steps[2], CooldownStep)
        assert w.steps[2].duration.seconds == 600

    def test_lap_button(self):
        text = "WARMUP: lap_button\nCOOLDOWN: lap_button"
        w = parse_dsl("Lap test", text)
        warmup, cooldown = w.steps
        assert isinstance(warmup, WarmupStep)
        assert isinstance(cooldown, CooldownStep)
        assert warmup.duration.lap_button is True
        assert cooldown.duration.lap_button is True

    def test_distance_steps(self):
        text = """
WARMUP: 2km
REPEAT: 8
  INTERVAL: 1km @ 3:50-4:00/km
  RECOVERY: 400m @ no_target
COOLDOWN: 2km
"""
        w = parse_dsl("8x1km", text)
        repeat = w.steps[1]
        assert isinstance(repeat, RepeatBlock)
        assert repeat.steps[0].duration.distance_m == 1000
        assert repeat.steps[1].duration.distance_m == 400

    def test_comment_lines_ignored(self):
        text = """
# This is a comment
WARMUP: 5min
# Another comment
COOLDOWN: 5min
"""
        w = parse_dsl("comment test", text)
        assert len(w.steps) == 2

    def test_unknown_keyword_raises(self):
        with pytest.raises(ValueError, match="Unknown keyword"):
            parse_dsl("fail", "JUNK: 10min")

    def test_invalid_pace_order_raises(self):
        # Pace min must be faster (smaller) than max
        text = "WARMUP: 5min\nREPEAT: 5\n  INTERVAL: 1min @ 4:25-4:10/km\nCOOLDOWN: 5min"
        with pytest.raises(ValueError, match="Pace range invalid"):
            parse_dsl("bad pace", text)
