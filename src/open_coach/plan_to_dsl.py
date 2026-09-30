"""Convert a PlannedWorkout (free-text description + targets) into a DSLWorkout.

Pure logic, no I/O. Used by ``sync_upcoming_workouts`` to push plan sessions to
the watch without a human re-typing the DSL.

Design rule: **never invent structure**. If the description of a quality
session cannot be parsed into explicit sets, return ``None`` with a reason so
the coach pushes it by hand via ``build_and_push_workout``. Before 2026-09-11 a
heuristic turned "10 km dont 15 min @ M" ("dont" = French for "including")
into a single 7.5 km block at M pace —
that is exactly what this module must never do again.

Conventions applied (coaching-rules/references/dsl-conventions.md):
- Rule A: easy / long_run / recovery = ONE distance block, pace window, no
  warmup/cooldown.
- Rule B: quality sessions use lap_button warmup/cooldown.
- Rule B-quater: pace window = coaching target ±5 s/km.
- Rule D: the builder appends the final lap_button step; nothing to do here.

Supported description grammar (French or English):
- sets:      ``3×1 km @ T 4:16-4:20 r 2'``, ``8×400 m @ I 3:58-4:05 r 200 m jog``,
             ``6x1000m @ 3:55``, ``5×400 m @ 10K 4:12 r 200 m``
- embedded:  ``10 km dont 15 min @ M 4:37``, ``SL 22 km dont 6 km @ M``,
             ``10 km incl. 15 min @ M``, ``LR 22 km including 6 km @ M``
- pace:      ``4:37``, ``4:16-4:20``, ``(3:30-3:45/km)``, or a zone letter
             (E/M/T/I/R) resolved through ``paces`` (from ``vdot.training_paces``)
- recovery:  ``r 2'``, ``r 2'30``, ``r 90 s``, ``r 200 m``, ``rec 2'``, ``recovery 90 s``

The embedded keyword is deliberately narrow: ``with`` is NOT accepted, since
"with 2 km warmup" would be misread as an embedded block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from open_coach.models import PlannedWorkout
from open_coach.workout_dsl import (
    CooldownStep,
    DSLWorkout,
    Duration,
    IntervalStep,
    PaceTarget,
    RecoveryStep,
    RepeatBlock,
    WarmupStep,
    WorkoutStep,
)

PACE_TOLERANCE_S = 5  # Rule B-quater
EASY_WINDOW_SLOW_S = 25  # easy target 5:30 → window 5:25-5:55
MAX_NAME_LEN = 120

_ZONE_KEYS = {
    "E": "easy",
    "M": "marathon",
    "T": "threshold",
    "I": "interval",
    "R": "repetition",
}

# "3×1 km", "8×400 m", "6x1000m", "5 × 2 km"
_SET_RE = re.compile(
    r"(?P<reps>\d{1,2})\s*[×x]\s*(?P<dist>\d+(?:[.,]\d+)?)\s*(?P<unit>km|m)\b",
    re.IGNORECASE,
)
# "dont 15 min @", "dont 6 km @", "incl. 15 min @", "including 6 km @"
_EMBEDDED_RE = re.compile(
    r"\b(?:dont|incl\.?|including)\s+(?P<val>\d+(?:[.,]\d+)?)\s*(?P<unit>min|km|m)\b",
    re.IGNORECASE,
)
# single-digit minute paces only (2:xx–7:xx) — avoids matching "H+30", "41:30"
_PACE_RE = re.compile(
    r"(?<![\d:])(?P<a>[2-7]):(?P<as>\d{2})(?:\s*-\s*(?P<b>[2-7]):(?P<bs>\d{2}))?(?![\d:])"
)
_ZONE_LETTER_RE = re.compile(r"@\s*(?P<z>[EMTIR])\b")
_RECOVERY_RE = re.compile(
    r"\b(?:recovery|rec|r)\s*"
    r"(?:(?P<min>\d+)'(?P<sec>\d{2})?|(?P<secs>\d+)\s*(?:s|sec)\b|(?P<m>\d+)\s*m\b)",
    re.IGNORECASE,
)

_QUALITY_TYPES = {"tempo", "interval", "intervals", "fartlek"}
_STEADY_TYPES = {"easy", "long_run", "recovery"}


@dataclass(frozen=True)
class Conversion:
    """Result of a plan → DSL conversion."""

    dsl: DSLWorkout | None
    reason: str | None = None  # populated when dsl is None

    @property
    def ok(self) -> bool:
        return self.dsl is not None


# ── helpers ───────────────────────────────────────────────────────────────────


def _mmss(m: str, s: str) -> int:
    return int(m) * 60 + int(s)


def _pace_in(text: str) -> tuple[int, int] | None:
    """First explicit pace in *text* → (fast, slow) sec/km, widened by tolerance."""
    m = _PACE_RE.search(text)
    if not m:
        return None
    fast = _mmss(m.group("a"), m.group("as"))
    slow = _mmss(m.group("b"), m.group("bs")) if m.group("b") else fast
    return (min(fast, slow) - PACE_TOLERANCE_S, max(fast, slow) + PACE_TOLERANCE_S)


def _zone_pace(text: str, paces: dict[str, tuple[float, float]] | None) -> tuple[int, int] | None:
    """Pace from a zone letter (``@ M``) via the athlete's VDOT table."""
    m = _ZONE_LETTER_RE.search(text)
    if not m or not paces:
        return None
    key = _ZONE_KEYS[m.group("z").upper()]
    if key not in paces:
        return None
    fast, slow = paces[key]
    # Zone bands are already ranges; still apply the alert tolerance.
    return (round(fast) - PACE_TOLERANCE_S, round(slow) + PACE_TOLERANCE_S)


def _resolve_pace(
    segment: str,
    paces: dict[str, tuple[float, float]] | None,
    fallback: float | None,
) -> PaceTarget | None:
    window = _pace_in(segment) or _zone_pace(segment, paces)
    if window is None and fallback is not None:
        window = (round(fallback) - PACE_TOLERANCE_S, round(fallback) + PACE_TOLERANCE_S)
    if window is None:
        return None
    return PaceTarget(min_sec_per_km=window[0], max_sec_per_km=window[1])


def _recovery(segment: str) -> Duration | None:
    m = _RECOVERY_RE.search(segment)
    if not m:
        return None
    if m.group("min"):
        return Duration(seconds=int(m.group("min")) * 60 + int(m.group("sec") or 0))
    if m.group("secs"):
        return Duration(seconds=int(m.group("secs")))
    return Duration(distance_m=float(m.group("m")))


def _distance_m(val: str, unit: str) -> float:
    v = float(val.replace(",", "."))
    return v * 1000 if unit.lower() == "km" else v


def _name(workout: PlannedWorkout) -> str:
    return (workout.description or f"{workout.workout_type} run").strip()[:MAX_NAME_LEN]


# ── converters ────────────────────────────────────────────────────────────────


def _steady_block(workout: PlannedWorkout) -> Conversion:
    """Rule A: one distance block with an easy pace window."""
    if workout.target_distance_km is None or workout.target_pace_sec_per_km is None:
        return Conversion(None, "steady run without distance or pace target")
    pace = round(workout.target_pace_sec_per_km)
    block = RepeatBlock(
        count=1,
        steps=[
            IntervalStep(
                duration=Duration(distance_m=float(workout.target_distance_km) * 1000),
                pace=PaceTarget(
                    min_sec_per_km=pace - PACE_TOLERANCE_S,
                    max_sec_per_km=pace + EASY_WINDOW_SLOW_S,
                ),
            )
        ],
    )
    return Conversion(DSLWorkout(name=_name(workout), steps=[block]))


def _sets_from_description(
    text: str,
    paces: dict[str, tuple[float, float]] | None,
    fallback_pace: float | None,
) -> list[RepeatBlock] | str:
    """Parse every ``N×D`` set. Returns blocks, or a reason string on failure."""
    matches = list(_SET_RE.finditer(text))
    if not matches:
        return "no N×D set found in description"
    blocks: list[RepeatBlock] = []
    for i, m in enumerate(matches):
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[m.end() : seg_end]
        pace = _resolve_pace(segment, paces, fallback_pace if len(matches) == 1 else None)
        if pace is None:
            return f"no pace found for set {m.group(0)!r}"
        rec = _recovery(segment)
        steps: list[IntervalStep | RecoveryStep] = [
            IntervalStep(
                duration=Duration(distance_m=_distance_m(m.group("dist"), m.group("unit"))),
                pace=pace,
            )
        ]
        if rec is not None:
            steps.append(RecoveryStep(duration=rec))
        blocks.append(RepeatBlock(count=int(m.group("reps")), steps=steps))
    return blocks


def _embedded_block(
    text: str,
    paces: dict[str, tuple[float, float]] | None,
    fallback_pace: float | None,
) -> RepeatBlock | str:
    """Parse ``X km dont N min/km @ pace`` → one block at pace."""
    m = _EMBEDDED_RE.search(text)
    if not m:
        return "no 'dont|incl. N min/km @' block found"
    segment = text[m.end() :]
    pace = _resolve_pace(segment, paces, fallback_pace)
    if pace is None:
        return "embedded block without resolvable pace"
    unit = m.group("unit").lower()
    val = m.group("val").replace(",", ".")
    duration = (
        Duration(seconds=float(val) * 60)
        if unit == "min"
        else Duration(distance_m=_distance_m(val, unit))
    )
    return RepeatBlock(count=1, steps=[IntervalStep(duration=duration, pace=pace)])


def _quality(workout: PlannedWorkout, paces: dict[str, tuple[float, float]] | None) -> Conversion:
    """Rule B: lap warmup + parsed body + lap cooldown."""
    text = workout.description or ""
    body: list[WorkoutStep]
    if _SET_RE.search(text):
        sets = _sets_from_description(text, paces, workout.target_pace_sec_per_km)
        if isinstance(sets, str):
            return Conversion(None, sets)
        body = list(sets)
    elif _EMBEDDED_RE.search(text):
        block = _embedded_block(text, paces, workout.target_pace_sec_per_km)
        if isinstance(block, str):
            return Conversion(None, block)
        body = [block]
    else:
        return Conversion(
            None, "quality session without parsable structure (no N×D, no 'dont|incl.')"
        )

    steps: list[WorkoutStep] = [
        WarmupStep(duration=Duration(lap_button=True)),
        *body,
        CooldownStep(duration=Duration(lap_button=True)),
    ]
    return Conversion(DSLWorkout(name=_name(workout), steps=steps))


def carries_quality(workout: PlannedWorkout) -> bool:
    """True when the session has a structure worth a watch workout.

    Quality types (tempo, intervals, fartlek), races, and steady runs with an
    embedded pace block (``SL 22 km dont 6 km @ M``). Plain easy, recovery and
    long runs are run on feel and are not pushed by default.
    """
    wtype = (workout.workout_type or "").lower()
    if wtype in _QUALITY_TYPES or wtype == "race":
        return True
    return wtype in _STEADY_TYPES and bool(_EMBEDDED_RE.search(workout.description or ""))


def convert_planned_workout(
    workout: PlannedWorkout,
    paces: dict[str, tuple[float, float]] | None = None,
) -> Conversion:
    """Convert a plan session to a DSLWorkout, or explain why it cannot be.

    Args:
        workout: Planned session from the active plan.
        paces: ``vdot.training_paces(vdot)`` output, used to resolve zone
            letters (``@ M``) when the description has no numeric pace.
    """
    wtype = (workout.workout_type or "").lower()
    text = workout.description or ""

    if wtype in _STEADY_TYPES:
        # A long run with an embedded M block is a quality session (Rule C).
        if _EMBEDDED_RE.search(text):
            # M-pace inside a long run: the plan's target pace is the *easy*
            # pace, never fall back to it for the embedded block.
            block = _embedded_block(text, paces, None)
            if isinstance(block, str):
                return Conversion(None, block)
            return Conversion(
                DSLWorkout(
                    name=_name(workout),
                    steps=[
                        WarmupStep(duration=Duration(lap_button=True)),
                        block,
                        CooldownStep(duration=Duration(lap_button=True)),
                    ],
                )
            )
        return _steady_block(workout)

    if wtype in _QUALITY_TYPES:
        return _quality(workout, paces)

    return Conversion(None, f"workout type {wtype!r} is not pushed automatically")
