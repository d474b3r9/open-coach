"""Strava OAuth2 authentication wrapper.

Token-first: reads cached tokens from ~/.open-coach/strava_tokens.json,
auto-refreshes the access token when it has expired (or is within 5 min
of expiring). First-time setup is handled out-of-band by
``scripts/strava_setup.py`` — this module never opens a browser.

Token file format (matches Strava's /oauth/token response):
    {
      "access_token":  "...",
      "refresh_token": "...",
      "expires_at":    1746201600,   # unix epoch seconds
      "athlete_id":    12345         # optional, populated at first save
    }
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

from open_coach.exceptions import StravaError
from open_coach.paths import DATA_DIR, env_credential

logger = logging.getLogger(__name__)

TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
DEFAULT_TOKEN_FILE = DATA_DIR / "strava_tokens.json"
REFRESH_LEEWAY_S = 300  # refresh if access token expires within 5 minutes


class StravaAuthError(StravaError):
    """Raised when Strava authentication cannot proceed."""


def _http_post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))


def load_tokens(path: Path = DEFAULT_TOKEN_FILE) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return cast(dict[str, Any], json.loads(path.read_text()))


def save_tokens(tokens: dict[str, Any], path: Path = DEFAULT_TOKEN_FILE) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=2))
    path.chmod(0o600)


def _refresh(refresh_token: str, client_id: str, client_secret: str) -> dict[str, Any]:
    return _http_post_form(
        TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )


def get_access_token(token_path: Path = DEFAULT_TOKEN_FILE) -> str:
    """Return a valid Strava access token, refreshing it if needed.

    Reads tokens from disk, refreshes via Strava's OAuth endpoint when the
    cached access token is close to expiry, and rewrites the cache so the
    rotated refresh_token is persisted.

    Raises:
        StravaAuthError: No cache (run ``scripts/strava_setup.py`` first)
            or refresh failed (e.g. user revoked access).
    """
    tokens = load_tokens(token_path)
    if tokens is None:
        raise StravaAuthError(
            f"No Strava tokens at {token_path}. "
            "Run `python scripts/strava_setup.py` once to authorize."
        )

    expires_at = int(tokens.get("expires_at", 0))
    if expires_at - REFRESH_LEEWAY_S > time.time():
        return cast(str, tokens["access_token"])

    client_id = env_credential("STRAVA_CLIENT_ID")
    client_secret = env_credential("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise StravaAuthError(
            "Strava access token expired and STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET "
            "are not set — cannot refresh."
        )

    logger.info("Strava: access token expired, refreshing")
    try:
        fresh = _refresh(tokens["refresh_token"], client_id, client_secret)
    except Exception as err:
        raise StravaAuthError(f"Strava token refresh failed: {err}") from err

    tokens["access_token"] = fresh["access_token"]
    tokens["refresh_token"] = fresh["refresh_token"]
    tokens["expires_at"] = fresh["expires_at"]
    save_tokens(tokens, token_path)
    return cast(str, tokens["access_token"])
