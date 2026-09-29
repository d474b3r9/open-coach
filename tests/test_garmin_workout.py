"""Tests for providers.garmin_workout — DSL to Garmin RunningWorkout conversion."""

from __future__ import annotations

import pytest
from garminconnect.workout import ExecutableStep, RepeatGroup, RunningWorkout

from open_coach.providers.garmin_workout import build_running_workout
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


def _make_interval_workout(n: int = 10) -> DSLWorkout:
    return DSLWorkout(
        name=f"{n}x1min threshold",
        steps=[
            WarmupStep(duration=Duration(seconds=600)),
            RepeatBlock(
                count=n,
                steps=[
                    IntervalStep(
                        duration=Duration(seconds=60),
                        pace=PaceTarget(min_sec_per_km=246, max_sec_per_km=261),
                    ),
                    RecoveryStep(duration=Duration(seconds=60)),
                ],
            ),
            CooldownStep(duration=Duration(seconds=600)),
        ],
    )


class TestBuildRunningWorkout:
    def test_returns_running_workout(self):
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        assert isinstance(result, RunningWorkout)

    def test_workout_name(self):
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        assert result.workoutName == "10x1min threshold"

    def test_estimated_duration(self):
        dsl = _make_interval_workout(10)
        result = build_running_workout(dsl)
        # warmup 600 + 10*(60+60) + cooldown 600 = 2400
        assert result.estimatedDurationInSecs == 2400

    def test_single_segment(self):
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        assert len(result.workoutSegments) == 1
        assert result.workoutSegments[0].sportType["sportTypeKey"] == "running"

    def test_top_level_step_count(self):
        # warmup + repeat_group + cooldown(10min) + auto lap-button finish = 4
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        steps = result.workoutSegments[0].workoutSteps
        assert len(steps) == 4

    def test_appends_lap_button_finish_when_missing(self):
        dsl = _make_interval_workout()  # cooldown is time-based → not open-ended
        result = build_running_workout(dsl)
        last = result.workoutSegments[0].workoutSteps[-1]
        assert isinstance(last, ExecutableStep)
        assert last.stepType["stepTypeKey"] == "cooldown"
        assert last.endCondition["conditionTypeKey"] == "lap.button"
        assert last.targetType["workoutTargetTypeKey"] == "no.target"

    def test_no_duplicate_finish_when_dsl_already_ends_on_lap(self):
        dsl = DSLWorkout(
            name="easy run",
            steps=[
                RepeatBlock(
                    count=1,
                    steps=[
                        IntervalStep(
                            duration=Duration(distance_m=8000),
                            pace=PaceTarget(min_sec_per_km=325, max_sec_per_km=355),
                        )
                    ],
                ),
                CooldownStep(duration=Duration(lap_button=True)),
            ],
        )
        steps = build_running_workout(dsl).workoutSegments[0].workoutSteps
        assert len(steps) == 2
        assert steps[-1].endCondition["conditionTypeKey"] == "lap.button"

    def test_single_block_easy_run_gets_lap_finish(self):
        dsl = DSLWorkout(
            name="easy run",
            steps=[
                RepeatBlock(
                    count=1,
                    steps=[IntervalStep(duration=Duration(distance_m=8000), pace=None)],
                )
            ],
        )
        steps = build_running_workout(dsl).workoutSegments[0].workoutSteps
        assert len(steps) == 2
        assert steps[-1].endCondition["conditionTypeKey"] == "lap.button"

    def test_warmup_step_type(self):
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        warmup = result.workoutSegments[0].workoutSteps[0]
        assert isinstance(warmup, ExecutableStep)
        assert warmup.stepType["stepTypeKey"] == "warmup"

    def test_cooldown_step_type(self):
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        cooldown = result.workoutSegments[0].workoutSteps[2]
        assert isinstance(cooldown, ExecutableStep)
        assert cooldown.stepType["stepTypeKey"] == "cooldown"

    def test_repeat_group(self):
        dsl = _make_interval_workout(8)
        result = build_running_workout(dsl)
        repeat = result.workoutSegments[0].workoutSteps[1]
        assert isinstance(repeat, RepeatGroup)
        assert repeat.numberOfIterations == 8
        assert len(repeat.workoutSteps) == 2

    def test_interval_step_time_condition(self):
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        repeat = result.workoutSegments[0].workoutSteps[1]
        interval = repeat.workoutSteps[0]
        assert interval.endCondition["conditionTypeKey"] == "time"
        assert interval.endConditionValue == 60.0

    def test_interval_pace_target(self):
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        repeat = result.workoutSegments[0].workoutSteps[1]
        interval = repeat.workoutSteps[0]
        target = interval.targetType
        # pace.zone (id=6) — Garmin displays as min:sec/km natively (vs km/h for speed.zone id=5)
        assert target["workoutTargetTypeId"] == 6
        assert target["workoutTargetTypeKey"] == "pace.zone"
        # pace.zone convention inverts speed.zone: valueOne = faster (higher m/s)
        assert interval.targetValueOne == pytest.approx(1000 / 246, rel=1e-2)
        assert interval.targetValueTwo == pytest.approx(1000 / 261, rel=1e-2)
        assert interval.targetValueOne > interval.targetValueTwo

    def test_recovery_no_target(self):
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        repeat = result.workoutSegments[0].workoutSteps[1]
        recovery = repeat.workoutSteps[1]
        assert recovery.targetType["workoutTargetTypeKey"] == "no.target"

    def test_lap_button_condition(self):
        dsl = DSLWorkout(
            name="Lap test",
            steps=[
                WarmupStep(duration=Duration(lap_button=True)),
                CooldownStep(duration=Duration(lap_button=True)),
            ],
        )
        result = build_running_workout(dsl)
        warmup = result.workoutSegments[0].workoutSteps[0]
        assert warmup.endCondition["conditionTypeKey"] == "lap.button"
        assert warmup.endConditionValue is None

    def test_distance_condition(self):
        dsl = DSLWorkout(
            name="Distance test",
            steps=[
                RepeatBlock(
                    count=5,
                    steps=[
                        IntervalStep(duration=Duration(distance_m=1000)),
                        RecoveryStep(duration=Duration(distance_m=400)),
                    ],
                )
            ],
        )
        result = build_running_workout(dsl)
        repeat = result.workoutSegments[0].workoutSteps[0]
        interval = repeat.workoutSteps[0]
        assert interval.endCondition["conditionTypeKey"] == "distance"
        assert interval.endConditionValue == 1000.0
        recovery = repeat.workoutSteps[1]
        assert recovery.endConditionValue == 400.0

    def test_to_dict_is_serializable(self):
        """Ensure the payload can be serialized to dict (for API upload)."""
        dsl = _make_interval_workout()
        result = build_running_workout(dsl)
        payload = result.to_dict()
        assert isinstance(payload, dict)
        assert "workoutName" in payload
        assert "workoutSegments" in payload

    def test_roundtrip_from_text_dsl(self):
        """Parse from text, build, serialize — no errors."""
        text = """
WARMUP: 10min
REPEAT: 6
  INTERVAL: 3min @ 4:00-4:15/km
  RECOVERY: 3min @ no_target
COOLDOWN: 10min
"""
        dsl = parse_dsl("6x3min I", text)
        result = build_running_workout(dsl)
        payload = result.to_dict()
        assert payload["workoutName"] == "6x3min I"
        segments = payload["workoutSegments"]
        assert len(segments) == 1
        steps = segments[0]["workoutSteps"]
        assert len(steps) == 4  # warmup, repeat, cooldown, auto lap-button finish
