"""One time convention for every machine: store UTC, show the PC's local time.

Instants the coach persists (``created_at``, ``updated_at``, ``recorded_at``…)
are timezone-aware UTC datetimes, serialized as ``2026-10-19T15:04:05Z``. A file
moved between Windows, Linux and macOS, or between two time zones, therefore
means the same instant everywhere, and "which file is newer" is exact.

This module is the only place that reads the system clock (a test enforces it):

- ``utcnow()`` replaces ``datetime.now()``: the instant to store.
- ``local_today()`` replaces ``date.today()``: the athlete's calendar day, in the
  timezone of the PC. Race dates, session dates and "today" in the tools are
  calendar days of the athlete, not instants.
- ``to_local()`` converts an instant to the PC's timezone for anything shown to a
  human (plan markdown, summaries).
- ``UtcDatetime`` is the model field type: it also accepts the naive values of
  files written by older versions (read as the local time of the PC that reads
  them, which is the PC that wrote them in the usual single-machine case) and
  any offset-aware value, and normalizes them to UTC.

The watch's own activity times (``start_time_local``) are wall-clock strings
from the vendor, used to bucket sessions by day: they are left as they are.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import AfterValidator


def utcnow() -> datetime:
    """The current instant as an aware UTC datetime."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """*value* as an aware UTC datetime (a naive value is read as this PC's local time)."""
    return value.astimezone(UTC)  # naive: astimezone() assumes the system timezone


def to_local(value: datetime) -> datetime:
    """*value* in this PC's timezone (a naive value is read as local already)."""
    return value.astimezone()


def local_today() -> date:
    """Today's calendar date in this PC's timezone."""
    return to_local(utcnow()).date()


UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
