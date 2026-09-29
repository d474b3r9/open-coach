"""Thin Strava API v3 client — only the endpoints the coach needs.

Stays stdlib-only (urllib) to match the project's "minimal deps" stance.
The client is created once per server lifespan and re-uses the access
token from ``strava_auth.get_access_token`` (which auto-refreshes).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from open_coach.strava_auth import DEFAULT_TOKEN_FILE, get_access_token

logger = logging.getLogger(__name__)

API_BASE = "https://www.strava.com/api/v3"
PAGE_SIZE = 100  # Strava max is 200; 100 keeps payloads small enough


class StravaClient:
    """Authenticated Strava API client. Construct once, re-use for the session."""

    def __init__(self, token_path: Path = DEFAULT_TOKEN_FILE):
        self._token_path = token_path

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = get_access_token(self._token_path)
        url = f"{API_BASE}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_activities(
        self,
        months: int = 6,
        activity_type: str | None = "Run",
    ) -> list[dict[str, Any]]:
        """Fetch activities from the last ``months`` months.

        Args:
            months: Lookback window in months (default 6).
            activity_type: Filter by Strava activity type (e.g. "Run", "Ride").
                Set ``None`` to return every activity type.

        Returns a list of simplified dicts ordered most-recent-first.
        """
        after_dt = datetime.now(UTC) - timedelta(days=months * 30)
        after_epoch = int(after_dt.timestamp())

        results: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._get(
                "/athlete/activities",
                {"after": after_epoch, "per_page": PAGE_SIZE, "page": page},
            )
            if not batch:
                break
            results.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            page += 1
            time.sleep(0.2)  # be polite — Strava enforces 100 req / 15 min

        if activity_type:
            results = [a for a in results if a.get("type") == activity_type]

        # Strava returns ascending order when `after` is set — flip to most-recent-first.
        results.reverse()
        return [_simplify(a) for a in results]


def _simplify(a: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw Strava activity dict to the fields the coach actually uses."""
    distance_m = a.get("distance") or 0
    moving_s = a.get("moving_time") or 0
    elapsed_s = a.get("elapsed_time") or 0
    avg_pace = (moving_s / (distance_m / 1000)) if distance_m > 0 else None
    return {
        "activity_id": a.get("id"),
        "name": a.get("name", ""),
        "type": a.get("type"),
        "sport_type": a.get("sport_type"),
        "date": a.get("start_date_local", ""),
        "distance_m": distance_m,
        "moving_time_s": moving_s,
        "elapsed_time_s": elapsed_s,
        "avg_pace_sec_per_km": avg_pace,
        "avg_speed_mps": a.get("average_speed"),
        "max_speed_mps": a.get("max_speed"),
        "avg_hr": a.get("average_heartrate"),
        "max_hr": a.get("max_heartrate"),
        "avg_cadence": a.get("average_cadence"),
        "elevation_gain_m": a.get("total_elevation_gain"),
        "calories": a.get("kilojoules"),  # Strava omits calories on /activities list
        "suffer_score": a.get("suffer_score"),
        "kudos": a.get("kudos_count"),
        "trainer": a.get("trainer", False),
        "commute": a.get("commute", False),
        "manual": a.get("manual", False),
    }


def get_strava_client(token_path: Path = DEFAULT_TOKEN_FILE) -> StravaClient | None:
    """Return a Strava client if tokens are on disk, else None.

    Mirrors the soft-fail pattern of the watch providers: missing auth means
    the server keeps running, the tool just reports "not connected".
    """
    if not token_path.exists():
        logger.info("Strava: no token cache, integration disabled")
        return None
    return StravaClient(token_path)
