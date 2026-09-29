"""Garmin Connect implementation of ``WatchProvider``.

The only place (with ``garmin_auth.py`` and ``garmin_workout.py``) that knows the
garminconnect client and Garmin payload shapes. Every call runs in a worker
thread: garminconnect is synchronous.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from open_coach.models import PersonalRecord
from open_coach.providers.base import (
    ActivityDetail,
    DailyHeartRate,
    RecoverySignals,
    RunActivity,
    WatchWorkout,
)
from open_coach.vdot import HALF_MARATHON_M, MARATHON_M

if TYPE_CHECKING:
    from garminconnect import Garmin

    from open_coach.workout_dsl import DSLWorkout

logger = logging.getLogger(__name__)

NOT_CONNECTED = "Garmin client not connected. Set GARMIN_EMAIL and GARMIN_PASSWORD."


def connect() -> GarminProvider | None:
    """Authenticate with Garmin Connect (token cache first); None when offline."""
    from open_coach.providers.garmin_auth import GarminAuthError, get_garmin_client

    try:
        client = get_garmin_client()
    except GarminAuthError as err:
        logger.warning("Garmin Connect: credentials not set — running offline. (%s)", err)
        return None
    except Exception as err:
        logger.warning("Garmin Connect: login failed — running offline. (%s)", err)
        return None
    logger.info("Garmin Connect: authenticated ✓")
    return GarminProvider(client)


# Garmin Connect personal-record typeIds for running distance PRs.
# value field holds the finish time in seconds, distance is the canonical
# distance for the type (so a watch overrun on a race activity does not pollute
# the PR pace).
GARMIN_PR_TYPEIDS = {
    3: ("5K", 5000.0),
    4: ("10K", 10000.0),
    5: ("half_marathon", HALF_MARATHON_M),
    6: ("marathon", MARATHON_M),
}


def parse_garmin_personal_records(raw: Any) -> list[PersonalRecord]:
    """Map ``Garmin.get_personal_record()`` entries to PersonalRecord.

    Garmin computes these from lap splits, not raw activity totals, so they
    are not polluted by uncut watches after the finish line. Entries with an
    unknown type, a missing time or an unparsable date are skipped.
    """
    prs: list[PersonalRecord] = []
    for entry in raw or []:
        type_id = entry.get("typeId")
        mapping = GARMIN_PR_TYPEIDS.get(type_id)
        if mapping is None:
            continue
        label, distance_m = mapping
        time_s = entry.get("value")
        activity_id = entry.get("activityId") or 0
        when = entry.get("prStartTimeGmtFormatted") or entry.get("prStartTimeGmt")
        if not isinstance(time_s, int | float) or time_s <= 0:
            continue
        try:
            if isinstance(when, str):
                pr_date = date.fromisoformat(when[:10])
            elif isinstance(when, int | float):
                # epoch millis
                pr_date = datetime.fromtimestamp(when / 1000.0).date()
            else:
                continue
        except (ValueError, OSError):
            continue
        prs.append(
            PersonalRecord(
                distance_label=label,
                distance_m=distance_m,
                time_s=float(time_s),
                pace_sec_per_km=float(time_s) / (distance_m / 1000.0),
                activity_id=int(activity_id),
                date=pr_date,
                source="platform_pr",
            )
        )
    return prs


def _run_from_garmin(a: dict[str, Any]) -> RunActivity:
    return RunActivity(
        activity_id=a.get("activityId"),
        name=a.get("activityName") or "",
        start_time_local=a.get("startTimeLocal") or "",
        distance_m=a.get("distance") or 0.0,
        duration_s=a.get("duration") or 0.0,
        avg_hr=a.get("averageHR"),
        max_hr=a.get("maxHR"),
        elevation_gain_m=a.get("elevationGain"),
        calories=a.get("calories"),
    )


class GarminProvider:
    """``WatchProvider`` backed by an authenticated garminconnect client."""

    name = "garmin"

    def __init__(self, client: Garmin) -> None:
        self.client = client

    # ── activities ──

    async def list_runs(self, start: date, end: date) -> list[RunActivity]:
        raw = await asyncio.to_thread(
            self.client.get_activities_by_date, start.isoformat(), end.isoformat(), "running"
        )
        return [_run_from_garmin(a) for a in raw or []]

    async def activity_detail(self, activity_id: int) -> ActivityDetail:
        details = await asyncio.to_thread(self.client.get_activity, activity_id)
        splits = await asyncio.to_thread(self.client.get_activity_splits, activity_id)
        summary = details.get("summaryDTO", {})
        return ActivityDetail(
            distance_m=summary.get("distance") or 0.0,
            duration_s=summary.get("duration") or 0.0,
            avg_hr=summary.get("averageHR"),
            summary=summary,
            splits=splits,
        )

    async def personal_records(self) -> list[PersonalRecord]:
        """Garmin's own PRs; empty list on any API error (callers merge with detected PRs)."""
        try:
            raw = await asyncio.to_thread(self.client.get_personal_record)
        except Exception as err:
            logger.debug("Garmin personal records fetch failed: %s", err)
            return []
        return parse_garmin_personal_records(raw)

    # ── health ──

    async def daily_heart_rate(self, iso_date: str) -> DailyHeartRate:
        hr = await asyncio.to_thread(self.client.get_heart_rates, iso_date)
        hr = hr or {}
        return DailyHeartRate(resting_hr=hr.get("restingHeartRate"), max_hr=hr.get("maxHeartRate"))

    async def recovery_signals(self, iso_date: str) -> RecoverySignals:
        """HRV / sleep / stress; each sub-fetch fails independently (missing data is common)."""
        signals = RecoverySignals()

        try:
            hrv = await asyncio.to_thread(self.client.get_hrv_data, iso_date) or {}
            # garminconnect nests the averages under "hrvSummary"; keep the
            # top-level lookup as a fallback for older payload shapes.
            summary = hrv.get("hrvSummary") or hrv
            signals.hrv_weekly_avg = summary.get("weeklyAvg")
            signals.hrv_last_night = summary.get("lastNightAvg")
        except Exception as err:
            logger.debug("HRV fetch failed: %s", err)

        try:
            sleep = await asyncio.to_thread(self.client.get_sleep_data, iso_date)
            dto = sleep.get("dailySleepDTO", {})
            signals.sleep_score = dto.get("sleepScores", {}).get("overall", {}).get("value")
            signals.sleep_duration_s = dto.get("sleepTimeSeconds")
        except Exception as err:
            logger.debug("Sleep data fetch failed: %s", err)

        try:
            stress = await asyncio.to_thread(self.client.get_stress_data, iso_date)
            signals.avg_stress = stress.get("overallStressLevel")
        except Exception as err:
            logger.debug("Stress data fetch failed: %s", err)

        return signals

    async def training_status(self) -> dict[str, Any]:
        """Raw Garmin VO2max / training status / readiness for today; None per failed part.

        garminconnect takes the calendar date (``YYYY-MM-DD``) for all three —
        passing anything else raises ``ValueError`` and the part comes back None.
        """
        today = date.today().isoformat()
        result: dict[str, Any] = {}
        try:
            result["vo2max"] = await asyncio.to_thread(self.client.get_max_metrics, today)
        except Exception as err:
            logger.debug("VO2max fetch failed: %s", err)
            result["vo2max"] = None

        try:
            result["training_status"] = await asyncio.to_thread(
                self.client.get_training_status, today
            )
        except Exception as err:
            logger.debug("Training status fetch failed: %s", err)
            result["training_status"] = None

        try:
            result["training_readiness"] = await asyncio.to_thread(
                self.client.get_training_readiness, today
            )
        except Exception as err:
            logger.debug("Training readiness fetch failed: %s", err)
            result["training_readiness"] = None

        return result

    # ── structured workouts ──

    async def list_workouts(self, limit: int) -> list[WatchWorkout]:
        workouts = await asyncio.to_thread(self.client.get_workouts, start=0, limit=limit)
        return [
            WatchWorkout(workout_id=w["workoutId"], name=w.get("workoutName") or "", raw=w)
            for w in workouts or []
            if w.get("workoutId") is not None
        ]

    async def upload_workout(self, dsl: DSLWorkout) -> int:
        from open_coach.providers.garmin_workout import build_running_workout

        result = await asyncio.to_thread(
            self.client.upload_running_workout, build_running_workout(dsl)
        )
        workout_id: int = result["workoutId"]
        return workout_id

    async def schedule_workout(self, workout_id: int, iso_date: str) -> int:
        result = await asyncio.to_thread(self.client.schedule_workout, workout_id, iso_date)
        schedule_id: int = result.get("workoutScheduleId", result.get("scheduleId", 0))
        return schedule_id

    async def unschedule_workout(self, schedule_id: int) -> None:
        await asyncio.to_thread(self.client.unschedule_workout, schedule_id)

    async def delete_workout(self, workout_id: int) -> None:
        await asyncio.to_thread(self.client.delete_workout, workout_id)
