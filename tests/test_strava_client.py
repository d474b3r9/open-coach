"""Tests for open_coach.strava_client — pagination, `after=` reversal, errors.

The HTTP layer (urllib.request.urlopen) is fully mocked — zero network.
Token acquisition is stubbed at `strava_client.get_access_token`.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from open_coach import strava_client as sc
from open_coach.strava_auth import StravaAuthError
from open_coach.strava_client import PAGE_SIZE, StravaClient, get_strava_client


def _activity(i: int, activity_type: str = "Run") -> dict[str, Any]:
    """Raw Strava activity dict; higher `i` = more recent."""
    return {
        "id": i,
        "name": f"Activity {i}",
        "type": activity_type,
        "sport_type": activity_type,
        "start_date_local": f"2026-01-{(i % 28) + 1:02d}T07:00:00Z",
        "distance": 10000.0,
        "moving_time": 3000,
        "elapsed_time": 3100,
    }


class _FakeResponse(io.BytesIO):
    """Minimal context-manager response, as returned by urllib.request.urlopen."""

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Mock urlopen with canned pages; record every request made."""
    state: dict[str, Any] = {"pages": {}, "requests": []}

    def fake_urlopen(req: Any, timeout: float | None = None) -> _FakeResponse:
        state["requests"].append(req)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        page = int(query["page"][0])
        payload = state["pages"].get(page, [])
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(sc.time, "sleep", lambda _s: None)  # no politeness delay in tests
    monkeypatch.setattr(sc, "get_access_token", lambda _path: "test-token")
    return state


def test_fetch_activities_paginates_and_reverses(http: dict[str, Any]) -> None:
    """Two full+partial pages in ascending order → merged, result[0] most recent."""
    # Strava with `after=` returns ASCENDING chronological order.
    http["pages"] = {
        1: [_activity(i) for i in range(1, PAGE_SIZE + 1)],  # ids 1..100 (oldest)
        2: [_activity(i) for i in range(PAGE_SIZE + 1, PAGE_SIZE + 51)],  # ids 101..150
    }
    result = StravaClient(Path("/nonexistent")).fetch_activities(months=6)

    assert len(result) == 150
    # Documented gotcha: ascending input must come back most-recent-first.
    assert result[0]["activity_id"] == 150
    assert result[-1]["activity_id"] == 1
    ids = [a["activity_id"] for a in result]
    assert ids == sorted(ids, reverse=True)
    # Page 2 was short (< PAGE_SIZE) → no page-3 request.
    assert len(http["requests"]) == 2
    assert "Bearer test-token" in [req.get_header("Authorization") for req in http["requests"]]


def test_fetch_activities_stops_on_empty_page(http: dict[str, Any]) -> None:
    """A full page followed by an empty page → exactly two HTTP calls."""
    http["pages"] = {1: [_activity(i) for i in range(1, PAGE_SIZE + 1)], 2: []}
    result = StravaClient(Path("/nonexistent")).fetch_activities(months=1)
    assert len(result) == PAGE_SIZE
    assert len(http["requests"]) == 2


def test_fetch_activities_filters_type(http: dict[str, Any]) -> None:
    http["pages"] = {1: [_activity(1, "Ride"), _activity(2, "Run"), _activity(3, "Ride")]}
    client = StravaClient(Path("/nonexistent"))
    assert [a["activity_id"] for a in client.fetch_activities()] == [2]
    assert [a["activity_id"] for a in client.fetch_activities(activity_type=None)] == [3, 2, 1]


def test_fetch_activities_simplifies_fields(http: dict[str, Any]) -> None:
    http["pages"] = {1: [_activity(7)]}
    (row,) = StravaClient(Path("/nonexistent")).fetch_activities()
    assert row["activity_id"] == 7
    assert row["distance_m"] == 10000.0
    assert row["moving_time_s"] == 3000
    assert row["avg_pace_sec_per_km"] == pytest.approx(300.0)  # 3000 s / 10 km


def test_http_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "get_access_token", lambda _path: "test-token")

    def fake_urlopen(req: Any, timeout: float | None = None) -> _FakeResponse:
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        StravaClient(Path("/nonexistent")).fetch_activities()


def test_auth_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_path: Path) -> str:
        raise StravaAuthError("no tokens")

    monkeypatch.setattr(sc, "get_access_token", boom)
    with pytest.raises(StravaAuthError):
        StravaClient(Path("/nonexistent")).fetch_activities()


def test_get_strava_client_soft_fails_without_cache(tmp_path: Path) -> None:
    assert get_strava_client(tmp_path / "missing.json") is None
    token_file = tmp_path / "strava_tokens.json"
    token_file.write_text("{}")
    client = get_strava_client(token_file)
    assert isinstance(client, StravaClient)
