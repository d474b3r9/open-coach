"""Convert a DSLWorkout into a garminconnect RunningWorkout payload.

The Garmin Connect workout API represents workouts as a tree of steps.
This module translates the structured DSL into that tree format.

Step order numbering:
- Top-level steps are numbered 1, 2, 3, ...
- Steps inside a RepeatGroup are numbered 1, 2, ... (relative, within the group)

End conditions:
- lap_button → conditionTypeId=1, conditionTypeKey="lap.button"
- time       → conditionTypeId=2, conditionTypeKey="time",     value=seconds
- distance   → conditionTypeId=3, conditionTypeKey="distance", value=metres

Pace/speed targets (Garmin uses m/s):
- targetTypeId=4 ("speed.zone"), targetValueOne=slower m/s, targetValueTwo=faster m/s
"""

from __future__ import annotations

from garminconnect.workout import (
    ExecutableStep,
    RepeatGroup,
    RunningWorkout,
    WorkoutSegment,
    create_repeat_group,
)

from open_coach.workout_dsl import (
    CooldownStep,
    DSLWorkout,
    Duration,
    IntervalStep,
    PaceTarget,
    RecoveryStep,
    RepeatBlock,
    WarmupStep,
)

# ── Condition constants ───────────────────────────────────────────────────────

_COND_LAP_BUTTON = {
    "conditionTypeId": 1,
    "conditionTypeKey": "lap.button",
    "displayOrder": 1,
    "displayable": False,
}
_COND_TIME = {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
_COND_DISTANCE = {
    "conditionTypeId": 3,
    "conditionTypeKey": "distance",
    "displayOrder": 3,
    "displayable": True,
}

_TARGET_NO_TARGET = {
    "workoutTargetTypeId": 1,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}

_RUNNING_SPORT = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
_STEP_WARMUP = {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1}
_STEP_COOLDOWN = {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2}
_STEP_INTERVAL = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}
_STEP_RECOVERY = {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _end_condition(duration: Duration) -> tuple[dict, float | None]:
    """Return (endCondition dict, endConditionValue)."""
    if duration.lap_button:
        return _COND_LAP_BUTTON, None
    if duration.seconds is not None:
        return _COND_TIME, duration.seconds
    # distance
    return _COND_DISTANCE, duration.distance_m


def _pace_target_type(pace: PaceTarget | None) -> dict:
    """Return ONLY the targetType dict (without target values).

    The values (targetValueOne/Two) must be set at the **step level**,
    NOT inside the targetType dict — Garmin silently drops them otherwise.

    We use **`pace.zone` (id=6)**, not `speed.zone` (id=5). Despite both
    storing values as m/s, Garmin Connect renders them differently:
    - `pace.zone` → display as min:sec /km (what runners want)
    - `speed.zone` → display as km/h (good for cycling, weird for running)

    Note `garminconnect.workout.TargetType` enum mistakenly labels id=6 as
    `OPEN` — actually `pace.zone` per empirical Garmin Connect inspection
    of a manually-edited running workout.
    """
    if pace is None:
        return _TARGET_NO_TARGET
    return {
        "workoutTargetTypeId": 6,
        "workoutTargetTypeKey": "pace.zone",
        "displayOrder": 6,
    }


def _build_executable(
    step_type_dict: dict,
    duration: Duration,
    pace: PaceTarget | None,
    order: int,
) -> ExecutableStep:
    condition, value = _end_condition(duration)
    extra: dict = {}
    if pace is not None:
        slower_ms, faster_ms = pace.to_speed_ms()
        # For pace.zone, Garmin convention is INVERSE of speed.zone:
        # - targetValueOne = faster speed (m/s higher) = faster pace (min/km lower)
        # - targetValueTwo = slower speed (m/s lower) = slower pace (min/km higher)
        # Confirmed by inspecting a manually-edited workout in Garmin Connect web.
        extra["targetValueOne"] = faster_ms
        extra["targetValueTwo"] = slower_ms
    return ExecutableStep(
        stepOrder=order,
        stepType=step_type_dict,
        endCondition=condition,
        endConditionValue=value,
        targetType=_pace_target_type(pace),
        **extra,
    )


def _ends_with_lap_button(steps: list[ExecutableStep | RepeatGroup]) -> bool:
    """True when the last top-level step is an open-ended (lap.button) step."""
    if not steps:
        return False
    last = steps[-1]
    return (
        isinstance(last, ExecutableStep)
        and last.endCondition.get("conditionTypeKey") == "lap.button"
    )


# ── Public API ────────────────────────────────────────────────────────────────


def build_running_workout(dsl: DSLWorkout) -> RunningWorkout:
    """Convert a DSLWorkout to a garminconnect RunningWorkout ready for upload.

    Args:
        dsl: Validated DSLWorkout.

    Returns:
        RunningWorkout instance (call .to_dict() for the raw API payload).
    """
    top_steps: list[ExecutableStep | RepeatGroup] = []
    order = 1

    for step in dsl.steps:
        if isinstance(step, WarmupStep):
            top_steps.append(_build_executable(_STEP_WARMUP, step.duration, None, order))
            order += 1

        elif isinstance(step, CooldownStep):
            top_steps.append(_build_executable(_STEP_COOLDOWN, step.duration, None, order))
            order += 1

        elif isinstance(step, RepeatBlock):
            inner: list[ExecutableStep] = []
            inner_order = 1
            for inner_step in step.steps:
                if isinstance(inner_step, IntervalStep):
                    inner.append(
                        _build_executable(
                            _STEP_INTERVAL, inner_step.duration, inner_step.pace, inner_order
                        )
                    )
                elif isinstance(inner_step, RecoveryStep):
                    inner.append(
                        _build_executable(
                            _STEP_RECOVERY, inner_step.duration, inner_step.pace, inner_order
                        )
                    )
                inner_order += 1
            top_steps.append(create_repeat_group(step.count, inner, order))
            order += 1

    if not _ends_with_lap_button(top_steps):
        # Athlete convention: every workout ends on a lap press, never on an
        # automatic stop (see coaching-rules/references/dsl-conventions.md, Rule D).
        top_steps.append(_build_executable(_STEP_COOLDOWN, Duration(lap_button=True), None, order))

    return RunningWorkout(
        workoutName=dsl.name,
        estimatedDurationInSecs=dsl.estimated_duration_s,
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType=_RUNNING_SPORT,
                workoutSteps=top_steps,
            )
        ],
    )
