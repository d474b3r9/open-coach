"""Tests for open_coach.providers.garmin_auth — token-cache-first Garmin authentication.

Everything is mocked: no real garminconnect login, no SSO, no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

import open_coach.providers.garmin_auth as auth
from open_coach.providers.garmin_auth import GarminAuthError


class _FakeInnerClient:
    """Stands in for garminconnect's `Garmin.client` (garth) — records dump()."""

    def __init__(self) -> None:
        self.dumped_to: str | None = None

    def dump(self, path: str) -> None:
        self.dumped_to = path


# Dummy value for mocked login tests — not a real credential (ggignore).
FAKE_TEST_PASSWORD = "fake-test-password-not-a-secret"


class FakeGarmin:
    """Drop-in double for garminconnect.Garmin — records constructor and login args."""

    instances: ClassVar[list[FakeGarmin]] = []

    def __init__(self, email: str | None = None, password: str | None = None) -> None:
        self.email = email
        self.password = password
        self.login_calls: list[dict[str, Any]] = []
        self.client = _FakeInnerClient()
        FakeGarmin.instances.append(self)

    def login(self, tokenstore: str | None = None) -> None:
        self.login_calls.append({"tokenstore": tokenstore})


@pytest.fixture
def token_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the token cache to tmp_path and install the FakeGarmin double."""
    store = tmp_path / ".garth"
    monkeypatch.setattr(auth, "_TOKEN_STORE", store)
    monkeypatch.setattr(auth, "_TOKEN_FILE", store / "garmin_tokens.json")
    FakeGarmin.instances = []
    monkeypatch.setattr(auth, "Garmin", FakeGarmin)
    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    return store


def test_token_cache_hit_skips_sso(token_env: Path) -> None:
    """With a cached token file, no credentials are used — login(tokenstore=...) only."""
    token_env.mkdir(parents=True)
    (token_env / "garmin_tokens.json").write_text("{}")

    client = auth.get_garmin_client()

    assert isinstance(client, FakeGarmin)
    assert client.email is None  # no credential login
    assert client.password is None
    assert client.login_calls == [{"tokenstore": str(token_env)}]


def test_missing_cache_and_creds_raises(token_env: Path) -> None:
    """No token cache + no GARMIN_EMAIL/GARMIN_PASSWORD → GarminAuthError, no login."""
    with pytest.raises(GarminAuthError, match="GARMIN_EMAIL"):
        auth.get_garmin_client()
    assert FakeGarmin.instances == []  # no client was even constructed


@pytest.mark.parametrize("missing", ["GARMIN_EMAIL", "GARMIN_PASSWORD"])
def test_partial_creds_raise(
    token_env: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """One of the two credentials alone is not enough."""
    present = "GARMIN_PASSWORD" if missing == "GARMIN_EMAIL" else "GARMIN_EMAIL"
    monkeypatch.setenv(present, "value")
    with pytest.raises(GarminAuthError):
        auth.get_garmin_client()


def test_env_credential_login_persists_tokens(
    token_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First-time login: creds from env, login() called, tokens dumped to the store."""
    monkeypatch.setenv("GARMIN_EMAIL", "runner@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", FAKE_TEST_PASSWORD)

    client = auth.get_garmin_client()

    assert isinstance(client, FakeGarmin)
    assert client.email == "runner@example.com"
    assert client.password == FAKE_TEST_PASSWORD
    assert client.login_calls == [{"tokenstore": None}]  # plain login(), not cache resume
    assert client.client.dumped_to == str(token_env)
    assert token_env.is_dir()  # token store directory was created


@pytest.mark.parametrize("literal", ["${GARMIN_EMAIL}", "${GARMIN_EMAIL:-}", "<your-email>", "  "])
def test_unexpanded_placeholder_counts_as_unset(
    token_env: Path, monkeypatch: pytest.MonkeyPatch, literal: str
) -> None:
    """A literal ``${VAR}`` passed through by the MCP host must never reach SSO."""
    monkeypatch.setenv("GARMIN_EMAIL", literal)
    monkeypatch.setenv("GARMIN_PASSWORD", FAKE_TEST_PASSWORD)
    with pytest.raises(GarminAuthError):
        auth.get_garmin_client()
    assert FakeGarmin.instances == []


def test_env_credential_returns_real_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GARMIN_EMAIL", " runner@example.com ")
    assert auth.env_credential("GARMIN_EMAIL") == "runner@example.com"
    monkeypatch.delenv("GARMIN_EMAIL")
    assert auth.env_credential("GARMIN_EMAIL") == ""
