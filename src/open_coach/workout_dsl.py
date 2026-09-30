"""Workout DSL — structured, vendor-neutral description of a watch workout.

Every workout names its ``sport``; each step target is a ``Target`` (pace or
heart rate today) the sport must accept (``Sport.target_kinds``).

Pydantic models representing the DSL semantics, plus a text parser
for the compact notation used in skills and documentation.

Text format example:
    WARMUP: 10min
    REPEAT: 10
      INTERVAL: 1min @ 4:10-4:25/km
      RECOVERY: 90s @ no_target
    COOLDOWN: 10min

Duration tokens:
    Xmin  → time (X minutes)
    Xs    → time (X seconds)
    Xkm   → distance (X kilometres)
    Xm    → distance (X metres)   [distinguish from "min" by trailing 'm' only]
    lap_button → open-ended, user presses lap key

Target tokens (after @):
    M:SS-M:SS/km  → PaceTarget (min=faster, max=slower)
    NNN-NNNbpm    → HeartRateTarget (min_bpm-max_bpm)
    no_target     → no target
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from open_coach.sports.base import SportKey

# ── Duration ──────────────────────────────────────────────────────────────────


class Duration(BaseModel):
    """Endpoint condition for a workout step."""

    seconds: float | None = None  # time-based
    distance_m: float | None = None  # distance-based
    lap_button: bool = False  # open-ended

    @model_validator(mode="after")
    def _exactly_one(self) -> Duration:
        active = sum(
            [
                self.seconds is not None,
                self.distance_m is not None,
                self.lap_button,
            ]
        )
        if active != 1:
            raise ValueError(
                "Duration must specify exactly one of: seconds, distance_m, lap_button"
            )
        return self

    def estimated_seconds(self, speed_mps: float) -> float:
        """Best-effort duration estimate; a distance is covered at *speed_mps*."""
        if self.seconds is not None:
            return self.seconds
        if self.distance_m is not None:
            return self.distance_m / speed_mps
        return 600  # lap_button → assume 10 min


# ── Targets ───────────────────────────────────────────────────────────────────


class PaceTarget(BaseModel):
    """Pace range in sec/km. min < max (faster bound < slower bound)."""

    kind: Literal["pace"] = "pace"
    min_sec_per_km: float = Field(gt=0)  # faster end
    max_sec_per_km: float = Field(gt=0)  # slower end

    @model_validator(mode="after")
    def _faster_first(self) -> PaceTarget:
        if self.min_sec_per_km >= self.max_sec_per_km:
            raise ValueError("min_sec_per_km (faster) must be < max_sec_per_km (slower)")
        return self

    def to_speed_ms(self) -> tuple[float, float]:
        """Return (slower_speed_ms, faster_speed_ms) in m/s, the unit watch APIs expect."""
        return (
            round(1000.0 / self.max_sec_per_km, 4),  # slower pace → lower speed
            round(1000.0 / self.min_sec_per_km, 4),  # faster pace → higher speed
        )


class HeartRateTarget(BaseModel):
    """Heart-rate range in bpm. min < max."""

    kind: Literal["heart_rate"] = "heart_rate"
    min_bpm: int = Field(gt=0)
    max_bpm: int = Field(gt=0)

    @model_validator(mode="after")
    def _low_first(self) -> HeartRateTarget:
        if self.min_bpm >= self.max_bpm:
            raise ValueError("min_bpm must be < max_bpm")
        return self


Target = Annotated[PaceTarget | HeartRateTarget, Field(discriminator="kind")]


# ── DSL step models ───────────────────────────────────────────────────────────


class WarmupStep(BaseModel):
    type: Literal["warmup"] = "warmup"
    duration: Duration


class CooldownStep(BaseModel):
    type: Literal["cooldown"] = "cooldown"
    duration: Duration


class IntervalStep(BaseModel):
    type: Literal["interval"] = "interval"
    duration: Duration
    target: Target | None = None  # None = no_target


class RecoveryStep(BaseModel):
    type: Literal["recovery"] = "recovery"
    duration: Duration
    target: Target | None = None  # None = no_target (recommended)


class RepeatBlock(BaseModel):
    type: Literal["repeat"] = "repeat"
    count: int = Field(ge=1, le=99)
    steps: list[Annotated[IntervalStep | RecoveryStep, Field(discriminator="type")]]

    @model_validator(mode="after")
    def _non_empty(self) -> RepeatBlock:
        if not self.steps:
            raise ValueError("RepeatBlock must contain at least one step")
        return self


# ── Top-level workout ─────────────────────────────────────────────────────────

WorkoutStep = Annotated[
    WarmupStep | RepeatBlock | CooldownStep,
    Field(discriminator="type"),
]


class DSLWorkout(BaseModel):
    """Complete workout description in structured DSL form."""

    sport: SportKey
    name: str = Field(min_length=1, max_length=120)
    steps: list[WorkoutStep]

    @model_validator(mode="after")
    def _validate_step_count(self) -> DSLWorkout:
        total = self._count_executable_steps()
        if total > 50:
            raise ValueError(f"Workout too long: max 50 steps per workout (got {total})")
        return self

    @model_validator(mode="after")
    def _validate_target_kinds(self) -> DSLWorkout:
        from open_coach.sports.registry import get_sport

        allowed = get_sport(self.sport).target_kinds
        for step in self.steps:
            inner = step.steps if isinstance(step, RepeatBlock) else []
            for s in inner:
                if s.target is not None and s.target.kind not in allowed:
                    raise ValueError(
                        f"{self.sport} workouts accept {sorted(allowed)} targets,"
                        f" not {s.target.kind!r}"
                    )
        return self

    def _count_executable_steps(self) -> int:
        count = 0
        for step in self.steps:
            if isinstance(step, RepeatBlock):
                count += 1 + len(step.steps)  # group + inner steps
            else:
                count += 1
        return count

    @property
    def estimated_duration_s(self) -> int:
        from open_coach.sports.registry import get_sport

        speed = get_sport(self.sport).default_speed_mps
        total = 0.0
        for step in self.steps:
            if isinstance(step, RepeatBlock):
                inner = sum(s.duration.estimated_seconds(speed) for s in step.steps)
                total += inner * step.count
            else:
                total += step.duration.estimated_seconds(speed)
        return int(total)


# ── Text parser ───────────────────────────────────────────────────────────────

_PACE_RE = re.compile(r"^(\d+):(\d{2})-(\d+):(\d{2})/km$")
_HR_RE = re.compile(r"^(\d+)-(\d+)\s*bpm$")


def _parse_duration(token: str) -> Duration:
    token = token.strip()
    if token == "lap_button":
        return Duration(lap_button=True)
    # Try units with letters
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(min|s|km|m)", token)
    if not m:
        raise ValueError(f"Invalid duration: {token!r}. Use Xmin, Xs, Xkm, Xm, or lap_button")
    value, unit = float(m.group(1)), m.group(2)
    if unit == "min":
        return Duration(seconds=value * 60)
    if unit == "s":
        return Duration(seconds=value)
    if unit == "km":
        return Duration(distance_m=value * 1000)
    # unit == "m"
    return Duration(distance_m=value)


def _parse_target(token: str) -> PaceTarget | HeartRateTarget | None:
    token = token.strip()
    if token == "no_target":
        return None
    hr = _HR_RE.fullmatch(token)
    if hr:
        return HeartRateTarget(min_bpm=int(hr.group(1)), max_bpm=int(hr.group(2)))
    m = _PACE_RE.fullmatch(token)
    if not m:
        raise ValueError(f"Invalid target: {token!r}. Use M:SS-M:SS/km, NNN-NNNbpm or no_target")
    min_s = int(m.group(1)) * 60 + int(m.group(2))
    max_s = int(m.group(3)) * 60 + int(m.group(4))
    if min_s >= max_s:
        raise ValueError("Pace range invalid: first value must be faster (smaller) than second")
    return PaceTarget(min_sec_per_km=float(min_s), max_sec_per_km=float(max_s))


def _parse_step_with_target(
    rest: str, step_cls: type[IntervalStep] | type[RecoveryStep]
) -> IntervalStep | RecoveryStep:
    """Parse INTERVAL or RECOVERY line content."""
    if "@" in rest:
        dur_str, target_str = rest.split("@", 1)
        dur = _parse_duration(dur_str.strip())
        target = _parse_target(target_str.strip())
    else:
        dur = _parse_duration(rest.strip())
        target = None
    return step_cls(duration=dur, target=target)


def parse_dsl(name: str, text: str, sport: SportKey) -> DSLWorkout:
    """Parse compact text DSL into a DSLWorkout.

    Args:
        name: Workout name.
        text: Multi-line DSL string.
        sport: Sport of the workout.

    Returns:
        Validated DSLWorkout.

    Raises:
        ValueError: On parse or validation errors.
    """
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    steps: list = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.upper().startswith("WARMUP:"):
            dur_str = stripped[7:].strip()
            steps.append(WarmupStep(duration=_parse_duration(dur_str)))
            i += 1

        elif stripped.upper().startswith("COOLDOWN:"):
            dur_str = stripped[9:].strip()
            steps.append(CooldownStep(duration=_parse_duration(dur_str)))
            i += 1

        elif stripped.upper().startswith("REPEAT:"):
            count = int(stripped[7:].strip())
            i += 1
            inner: list = []
            while i < len(lines):
                inner_line = lines[i]
                # Indented lines belong to the repeat block
                if not (inner_line.startswith("  ") or inner_line.startswith("\t")):
                    break
                inner_stripped = inner_line.strip()
                if inner_stripped.upper().startswith("INTERVAL:"):
                    rest = inner_stripped[9:].strip()
                    inner.append(_parse_step_with_target(rest, IntervalStep))
                elif inner_stripped.upper().startswith("RECOVERY:"):
                    rest = inner_stripped[9:].strip()
                    inner.append(_parse_step_with_target(rest, RecoveryStep))
                else:
                    raise ValueError(f"Unexpected line inside REPEAT block: {inner_stripped!r}")
                i += 1
            steps.append(RepeatBlock(count=count, steps=inner))

        else:
            raise ValueError(f"Unknown keyword on line {i + 1}: {stripped!r}")

    return DSLWorkout(sport=sport, name=name, steps=steps)
