"""Tests for open_coach.strava_auth — token cache, 5-min leeway, mocked refresh.

The token path is always an explicit tmp_path file (the module accepts a
``token_path`` parameter everywhere), so ~/.open-coach is never touched.
All HTTP is mocked at the `_http_post_form` boundary — zero network.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from open_coach import strava_auth
from open_coach.strava_auth import (
    StravaAuthError,
    get_access_token,
    load_tokens,
    save_tokens,
)


def _write_tokens(path: Path, expires_in_s: float) -> dict[str, Any]:
    tokens = {
        "access_token": "cached-access",
        "refresh_token": "cached-refresh",
        "expires_at": int(time.time() + expires_in_s),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens))
    return tokens


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    return tmp_path / "strava_tokens.json"


@pytest.fixture
def strava_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRAVA_CLIENT_ID", "cid")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "csecret")


@pytest.fixture
def no_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if anything tries to hit the network."""

    def _boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("unexpected HTTP call")

    monkeypatch.setattr(strava_auth, "_http_post_form", _boom)


# ── load/save ────────────────────────────────────────────────────────────────


def test_load_tokens_missing_returns_none(token_file: Path) -> None:
    assert load_tokens(token_file) is None


def test_save_and_load_roundtrip(token_file: Path) -> None:
    tokens = {"access_token": "a", "refresh_token": "r", "expires_at": 123}
    save_tokens(tokens, token_file)
    assert load_tokens(token_file) == tokens
    assert token_file.stat().st_mode & 0o777 == 0o600  # private file


# ── get_access_token ─────────────────────────────────────────────────────────


def test_missing_cache_raises(token_file: Path, no_http: None) -> None:
    with pytest.raises(StravaAuthError, match="No Strava tokens"):
        get_access_token(token_file)


def test_valid_token_no_refresh(token_file: Path, no_http: None) -> None:
    """Token expiring in 10 min (beyond the 5-min leeway) → returned as-is."""
    _write_tokens(token_file, expires_in_s=600)
    assert get_access_token(token_file) == "cached-access"


def test_token_within_leeway_triggers_refresh(
    token_file: Path, strava_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Token expiring in 4 min (< 5-min leeway) → refresh flow runs."""
    _write_tokens(token_file, expires_in_s=240)
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_post(url: str, data: dict[str, str]) -> dict[str, Any]:
        calls.append((url, data))
        return {
            "access_token": "fresh-access",
            "refresh_token": "fresh-refresh",
            "expires_at": int(time.time() + 6 * 3600),
        }

    monkeypatch.setattr(strava_auth, "_http_post_form", fake_post)

    assert get_access_token(token_file) == "fresh-access"
    assert len(calls) == 1
    url, data = calls[0]
    assert url == strava_auth.TOKEN_URL
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "cached-refresh"
    assert data["client_id"] == "cid"
    assert data["client_secret"] == "csecret"

    # Rotated tokens must be persisted back to disk
    persisted = json.loads(token_file.read_text())
    assert persisted["access_token"] == "fresh-access"
    assert persisted["refresh_token"] == "fresh-refresh"


def test_expired_token_without_client_creds_raises(
    token_file: Path, no_http: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("STRAVA_CLIENT_SECRET", raising=False)
    _write_tokens(token_file, expires_in_s=-10)
    with pytest.raises(StravaAuthError, match="cannot refresh"):
        get_access_token(token_file)


def test_refresh_failure_wrapped_in_strava_auth_error(
    token_file: Path, strava_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_tokens(token_file, expires_in_s=-10)

    def fake_post(url: str, data: dict[str, str]) -> dict[str, Any]:
        raise OSError("connection refused")

    monkeypatch.setattr(strava_auth, "_http_post_form", fake_post)
    with pytest.raises(StravaAuthError, match="refresh failed"):
        get_access_token(token_file)
    # Cache must not be clobbered by a failed refresh
    assert json.loads(token_file.read_text())["access_token"] == "cached-access"
