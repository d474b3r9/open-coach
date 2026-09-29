"""Tests for open_coach.server — coach_lifespan graceful degradation.

All external clients are monkeypatched: no Garmin SSO, no Strava HTTP, and
CoachStorage is redirected to tmp_path so ~/.open-coach is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_coach.providers.garmin_auth
import open_coach.server
import open_coach.strava_client
from open_coach.providers.garmin_auth import GarminAuthError
from open_coach.server import coach_lifespan
from open_coach.storage import CoachStorage


@pytest.fixture
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """coach_lifespan calls CoachStorage() with no args — redirect it to tmp_path."""
    base = tmp_path / "coach"
    monkeypatch.setattr(open_coach.server, "CoachStorage", lambda: CoachStorage(base_dir=base))
    return base


@pytest.fixture
def no_strava(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a missing Strava token cache (get_strava_client soft-fails to None)."""
    monkeypatch.setattr(open_coach.strava_client, "get_strava_client", lambda: None)


async def test_lifespan_degrades_when_garmin_auth_fails(
    isolated_storage: Path, no_strava: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GarminAuthError + no Strava cache → server still yields usable state."""

    def raise_auth() -> None:
        raise GarminAuthError("no credentials")

    monkeypatch.setattr(open_coach.providers.garmin_auth, "get_garmin_client", raise_auth)

    async with coach_lifespan(None) as state:  # type: ignore[arg-type]
        assert state["watch"] is None
        assert state["strava"] is None
        assert isinstance(state["storage"], CoachStorage)
        # ensure_dirs ran on the isolated base (sync Path check is fine in a test)
        assert isolated_storage.is_dir()


async def test_lifespan_survives_unexpected_garmin_error(
    isolated_storage: Path, no_strava: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any non-auth exception during Garmin login must also degrade to offline."""

    def raise_boom() -> None:
        raise RuntimeError("cloudflare says no")

    monkeypatch.setattr(open_coach.providers.garmin_auth, "get_garmin_client", raise_boom)

    async with coach_lifespan(None) as state:  # type: ignore[arg-type]
        assert state["watch"] is None
        assert state["strava"] is None


async def test_lifespan_survives_strava_init_failure(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash inside Strava init is caught — the rest of the state is intact."""
    garmin_sentinel = object()
    monkeypatch.setattr(
        open_coach.providers.garmin_auth, "get_garmin_client", lambda: garmin_sentinel
    )

    def strava_boom() -> None:
        raise OSError("token file unreadable")

    monkeypatch.setattr(open_coach.strava_client, "get_strava_client", strava_boom)

    async with coach_lifespan(None) as state:  # type: ignore[arg-type]
        assert state["watch"].client is garmin_sentinel
        assert state["strava"] is None


async def test_lifespan_passes_clients_through(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both clients initialize, they land unchanged in the lifespan state."""
    garmin_sentinel = object()
    strava_sentinel = object()
    monkeypatch.setattr(
        open_coach.providers.garmin_auth, "get_garmin_client", lambda: garmin_sentinel
    )
    monkeypatch.setattr(open_coach.strava_client, "get_strava_client", lambda: strava_sentinel)

    async with coach_lifespan(None) as state:  # type: ignore[arg-type]
        assert state["watch"].client is garmin_sentinel
        assert state["strava"] is strava_sentinel
