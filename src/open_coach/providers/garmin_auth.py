"""Garmin Connect authentication wrapper.

Token-first: reuses cached OAuth tokens at ~/.garth/ if present, falls
back to a fresh login via garminconnect's 5-strategy chain (curl_cffi
TLS rotation, mobile/widget/portal endpoints).

garminconnect 0.3.x stores its token cache as ~/.garth/garmin_tokens.json
(single JSON file). Note: garth's own token files (oauth1_token.json,
oauth2_token.json) live in the same directory but are NOT compatible —
do not seed the cache from a garth-only login.
"""

from __future__ import annotations

import logging
from pathlib import Path

from garminconnect import Garmin

from open_coach.exceptions import WatchAuthError
from open_coach.paths import env_credential

logger = logging.getLogger(__name__)


class GarminAuthError(WatchAuthError):
    """Garmin authentication failed or GARMIN_EMAIL / GARMIN_PASSWORD are missing."""


_TOKEN_STORE = Path.home() / ".garth"
_TOKEN_FILE = _TOKEN_STORE / "garmin_tokens.json"


def get_garmin_client() -> Garmin:
    """Return an authenticated Garmin client.

    Subsequent runs read tokens from disk (zero SSO call). First run logs in
    with GARMIN_EMAIL/GARMIN_PASSWORD and persists tokens for next time.

    Raises:
        GarminAuthError: First-time login but credentials missing.
        garminconnect.GarminConnectConnectionError: Login chain exhausted
            (typically Cloudflare CAPTCHA / IP rate-limit).
    """
    token_path = str(_TOKEN_STORE)

    if _TOKEN_FILE.exists():
        client = Garmin()
        client.login(tokenstore=token_path)
        logger.info("Garmin: session resumed from token cache (%s)", _TOKEN_FILE)
        return client

    email = env_credential("GARMIN_EMAIL")
    password = env_credential("GARMIN_PASSWORD")
    if not email or not password:
        raise GarminAuthError("GARMIN_EMAIL and GARMIN_PASSWORD must be set for first-time login.")

    logger.info("Garmin: first-time login for %s", email)
    client = Garmin(email=email, password=password)
    client.login()

    _TOKEN_STORE.mkdir(mode=0o700, parents=True, exist_ok=True)
    client.client.dump(token_path)
    logger.info("Garmin: tokens saved to %s", _TOKEN_FILE)
    return client
