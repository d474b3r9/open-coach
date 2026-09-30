"""Schema migrations for the JSON files in ~/.open-coach/.

``storage.py`` reads each file as a raw dict, runs ``migrate(kind, data)`` and
only then validates it against the current model. A migration step upgrades
one ``schema_version`` (from N to N+1) and is pure dict → dict: no model
import, so old files keep migrating after the models move on.

Adding a step: bump the model's ``schema_version`` default, write
``_<kind>_v<N>_to_v<N+1>`` and register it in ``_MIGRATIONS``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

Kind = Literal["profile", "goals", "feedback", "plan", "activity_cache"]
Data = dict[str, Any]

# v1 files predate sport plugins: everything in them is running.
_V1_SPORT = "running"


def _m(km: Any) -> float | None:
    """km → metres, None passes through."""
    return None if km is None else round(float(km) * 1000, 1)


def _pace(sec_per_km: Any) -> Data | None:
    return None if sec_per_km is None else {"kind": "pace_sec_per_km", "value": sec_per_km}


def _rename(d: Data, old: str, new: str, convert: Callable[[Any], Any] = lambda v: v) -> None:
    if old in d:
        d[new] = convert(d.pop(old))


# ── v1 → v2: sport plugins (running becomes one sport among others) ──


def _goal_v1(goal: Data) -> Data:
    goal.setdefault("sport", _V1_SPORT)
    return goal


def _profile_v1_to_v2(d: Data) -> Data:
    running: Data = {}
    vdot = d.pop("vdot", None)
    source = d.pop("vdot_source", None)
    if vdot:
        running["fitness"] = {"metric": "vdot", "value": vdot, "source": source}
    records = d.pop("personal_records", None) or []
    for pr in records:
        pr.pop("pace_sec_per_km", None)
    if records:
        running["personal_records"] = records
    pattern = d.pop("training_pattern", None)
    if pattern:
        _rename(pattern, "weekly_volume_km", "weekly_distance_m", _m)
        _rename(pattern, "long_run_avg_km", "long_session_avg_distance_m", _m)
        _rename(pattern, "easy_pace_avg_sec_per_km", "easy_intensity", _pace)
        running["training_pattern"] = pattern
    if running:
        d.setdefault("sports", {})[_V1_SPORT] = running
    return d


def _goals_v1_to_v2(d: Data) -> Data:
    for goal in d.get("goals", []):
        _goal_v1(goal)
    return d


def _feedback_v1_to_v2(d: Data) -> Data:
    for e in d.get("entries", []):
        e.setdefault("sport", _V1_SPORT)
        e.setdefault("workout_type", "easy")  # v1 default
        _rename(e, "planned_distance_km", "planned_distance_m", _m)
        _rename(e, "actual_distance_km", "actual_distance_m", _m)
        _rename(e, "planned_pace_sec_per_km", "planned_intensity", _pace)
        _rename(e, "actual_pace_sec_per_km", "actual_intensity", _pace)
    return d


def _volume(km: Any) -> Data:
    return {_V1_SPORT: {"distance_m": _m(km), "duration_s": 0.0}} if km else {}


def _plan_v1_to_v2(d: Data) -> Data:
    if isinstance(d.get("goal"), dict):
        _goal_v1(d["goal"])
    for week in d.get("weeks", []):
        _rename(week, "planned_volume_km", "planned_volume", _volume)
        _rename(week, "actual_volume_km", "actual_volume", _volume)
        for w in week.get("workouts", []):
            _rename(w, "target_distance_km", "target_distance_m", _m)
            _rename(
                w,
                "target_duration_min",
                "target_duration_s",
                lambda v: None if v is None else v * 60,
            )
            _rename(w, "target_pace_sec_per_km", "target_intensity", _pace)
            _rename(w, "actual_distance_km", "actual_distance_m", _m)
            _rename(w, "actual_pace_sec_per_km", "actual_intensity", _pace)
        for extra in week.get("extra_activities", []):
            extra.setdefault("sport", _V1_SPORT)
            _rename(extra, "distance_km", "distance_m", _m)
    return d


def _activity_cache_v1_to_v2(d: Data) -> Data:
    for a in d.get("activities", []):
        a.pop("avg_pace_sec_per_km", None)
        _rename(a, "activity_type", "sport")
        a.setdefault("sport", _V1_SPORT)
    return d


_MIGRATIONS: dict[tuple[Kind, int], Callable[[Data], Data]] = {
    ("profile", 1): _profile_v1_to_v2,
    ("goals", 1): _goals_v1_to_v2,
    ("feedback", 1): _feedback_v1_to_v2,
    ("plan", 1): _plan_v1_to_v2,
    ("activity_cache", 1): _activity_cache_v1_to_v2,
}


def migrate(kind: Kind, data: Data) -> tuple[Data, int | None]:
    """Upgrade *data* to the latest schema of *kind*, in place.

    Returns ``(data, from_version)`` where ``from_version`` is the version the
    file was read at, or None when no step ran (already current).
    """
    start = version = int(data.get("schema_version", 1))
    while (step := _MIGRATIONS.get((kind, version))) is not None:
        data = step(data)
        version += 1
        data["schema_version"] = version
    return data, (start if version != start else None)
