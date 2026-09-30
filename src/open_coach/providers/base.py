"""Watch-provider interface: what the coach needs from a watch platform.

Tools talk to a ``WatchProvider`` only, never to a vendor SDK. Each provider
(listed in ``providers/__init__.py``) owns the vendor client, its payload
formats and its workout format; the models below are the neutral shapes the
tools consume.

Error contract: methods may raise on transport/API errors — tools keep their
own soft-failure handling. ``recovery_signals`` and ``training_status`` are
best-effort aggregates and never raise (each sub-fetch fails independently).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from open_coach.sports.base import OTHER_SPORT, ActivitySport, SportKey

if TYPE_CHECKING:
    from datetime import date

    from open_coach.models import PersonalRecord
    from open_coach.workout_dsl import DSLWorkout


# int | float (not float): pydantic keeps the vendor's own number type, so an
# integer score is not re-serialised as 80.0.
Num = int | float


class Activity(BaseModel):
    """One recorded activity as listed by the watch platform."""

    activity_id: int | None = None
    sport: ActivitySport = OTHER_SPORT
    vendor_type: str = ""  # the platform's own activity type, e.g. "trail_running"
    name: str = ""
    start_time_local: str = ""  # ISO local timestamp; [:10] is the date
    distance_m: Num = 0.0
    duration_s: Num = 0.0
    avg_hr: Num | None = None
    max_hr: Num | None = None
    elevation_gain_m: Num | None = None
    calories: Num | None = None


class ActivityDetail(BaseModel):
    """One activity in detail: normalised totals plus the raw vendor payloads."""

    sport: ActivitySport = OTHER_SPORT
    distance_m: Num = 0.0
    duration_s: Num = 0.0
    avg_hr: Num | None = None
    # Raw vendor payloads, returned as-is to the LLM by get_activity_details.
    summary: dict[str, Any] = Field(default_factory=dict)
    splits: Any = None


class DailyHeartRate(BaseModel):
    resting_hr: Num | None = None
    max_hr: Num | None = None


class RecoverySignals(BaseModel):
    """HRV / sleep / stress scalars for one day (None = not available)."""

    hrv_weekly_avg: Num | None = None
    hrv_last_night: Num | None = None
    sleep_score: Num | None = None
    sleep_duration_s: Num | None = None
    avg_stress: Num | None = None


class WatchWorkout(BaseModel):
    """A workout template in the watch library."""

    workout_id: int
    name: str = ""
    # Raw vendor entry, returned as-is to the LLM by list_watch_workouts.
    raw: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class WatchProvider(Protocol):
    """Everything the coach reads from, or pushes to, a watch platform."""

    name: str

    # ── activities ──
    async def list_activities(
        self, start: date, end: date, sports: frozenset[SportKey] | None = None
    ) -> list[Activity]:
        """Activities between *start* and *end*; only *sports* when given (None = all)."""
        ...

    async def activity_detail(self, activity_id: int) -> ActivityDetail: ...
    async def personal_records(self) -> dict[SportKey, list[PersonalRecord]]:
        """The platform's own records, per sport (empty on any API error)."""
        ...

    # ── health ──
    async def daily_heart_rate(self, iso_date: str) -> DailyHeartRate: ...
    async def recovery_signals(self, iso_date: str) -> RecoverySignals: ...
    async def training_status(self) -> dict[str, Any]: ...

    # ── structured workouts ──
    async def list_workouts(self, limit: int) -> list[WatchWorkout]: ...
    async def upload_workout(self, dsl: DSLWorkout) -> int: ...
    async def schedule_workout(self, workout_id: int, iso_date: str) -> int: ...
    async def unschedule_workout(self, schedule_id: int) -> None: ...
    async def delete_workout(self, workout_id: int) -> None: ...
