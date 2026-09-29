"""Garmin SSO via SeleniumBase UC + DI token exchange (garminconnect 0.3.x format).

Flow:
1. SeleniumBase UC mode (non-instrumented Chrome) opens the Garmin mobile
   sign-in page → JS inside Chrome POSTs /sso/mobile/api/login → serviceTicketId
   (Cloudflare passes because it is a real Chrome)
2. With the serviceTicket: POST diauth.garmin.com/di-oauth2-service/oauth/token
   to exchange it for a DI Bearer token. Try each DI clientId in order
   (2025Q2 → 2024Q4 → ANDROID_DI → IOS_DI).
3. Extract client_id from the JWT (di_token).
4. Write ~/.garth/garmin_tokens.json in the `{di_token, di_refresh_token, di_client_id}`
   format compatible with garminconnect 0.3.x.

Credentials: --email / --password (CLI args, take precedence) or env vars
GARMIN_EMAIL / GARMIN_PASSWORD (fallback).

Prerequisite: MFA disabled on the Garmin account.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

if (
    isinstance(sys.stdout, io.TextIOWrapper)
    and sys.stdout.encoding
    and sys.stdout.encoding.lower() != "utf-8"
):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Same constants as garminconnect/client.py
CLIENT_ID_SSO = "GCM_ANDROID_DARK"  # for the SSO login
DI_TOKEN_URL = "https://diauth.garmin.com/di-oauth2-service/oauth/token"
DI_GRANT_TYPE = "https://connectapi.garmin.com/di-oauth2-service/oauth/grant/service_ticket"
DI_CLIENT_IDS = (
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2024Q4",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI",
    "GARMIN_CONNECT_MOBILE_IOS_DI",
)
MOBILE_SSO_SERVICE_URL = "https://mobile.integration.garmin.com/gcm/android"

NATIVE_API_USER_AGENT = (
    "com.garmin.android.apps.connectmobile/5.23; ; Google/sdk_gphone64_arm64/google; "
    "Android/33; Dalvik/2.1.0"
)

GARTH_DIR = Path.home() / ".garth"
TOKEN_FILE = GARTH_DIR / "garmin_tokens.json"


def step1_get_ticket_via_chrome(email: str, password: str) -> str:
    """SeleniumBase UC: open Chrome, POST /mobile/api/login via JS, return the ticket."""
    from seleniumbase import Driver

    print("[1/2] Spawning SeleniumBase UC Chrome (visible)...")
    driver = Driver(uc=True, headless=False, incognito=False)
    try:
        driver.set_script_timeout(60)

        sign_in_url = f"https://sso.garmin.com/mobile/sso/en/sign-in?clientId={CLIENT_ID_SSO}"
        print(f"      → loading {sign_in_url}")
        driver.uc_open_with_reconnect(sign_in_url, reconnect_time=4)
        time.sleep(3)

        title = driver.title
        cur = driver.current_url[:80]
        print(f"      page: {title!r} @ {cur}")

        js = """
        const callback = arguments[2];
        const email = arguments[0];
        const password = arguments[1];
        const params = new URLSearchParams({
          clientId: 'GCM_ANDROID_DARK',
          locale: 'en-US',
          service: 'https://mobile.integration.garmin.com/gcm/android'
        });
        const url = 'https://sso.garmin.com/mobile/api/login?' + params.toString();
        fetch(url, {
          method: 'POST',
          credentials: 'include',
          headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
          body: JSON.stringify({
            username: email, password: password, rememberMe: false, captchaToken: ''
          })
        })
        .then(r => r.text().then(text => ({status: r.status, text: text})))
        .then(o => {
          try { callback({ok: true, status: o.status, json: JSON.parse(o.text)}); }
          catch(e) {
            callback({ok: false, error: 'parse', status: o.status, body: o.text.slice(0, 600)});
          }
        })
        .catch(err => callback({ok: false, error: 'fetch', message: err.message}));
        """
        print("[1/2] Submitting POST /mobile/api/login via Chrome fetch()...")
        result = driver.execute_async_script(js, email, password)

        if not result or not result.get("ok"):
            raise RuntimeError(
                f"Login fetch failed: {result.get('error') if result else 'None'} | "
                f"status={result.get('status') if result else 'n/a'} | "
                f"body={(result or {}).get('body', (result or {}).get('message', '<empty>'))}"
            )

        json_resp = result["json"]
        status_obj = json_resp.get("responseStatus", {})
        resp_type = status_obj.get("type", "UNKNOWN")
        message = status_obj.get("message", "")

        if resp_type == "MFA_REQUIRED":
            raise RuntimeError(
                "MFA_REQUIRED — temporarily disable MFA in your Garmin settings "
                "(Account Security), retry, then re-enable it once "
                "garmin_tokens.json has been created."
            )
        if resp_type != "SUCCESSFUL":
            raise RuntimeError(
                f"Login not SUCCESSFUL: type={resp_type} message={message!r}\n"
                f"Full response: {json_resp}"
            )

        ticket: str = json_resp.get("serviceTicketId")
        if not ticket:
            raise RuntimeError(f"No serviceTicketId in response: {json_resp}")

        print(f"[1/2] ✅ serviceTicketId received (len={len(ticket)})")
        return ticket
    finally:
        with contextlib.suppress(Exception):
            driver.quit()


def _extract_client_id_from_jwt(jwt: str) -> str | None:
    """Decode the middle segment of a JWT and return its 'client_id' claim."""
    try:
        parts = jwt.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        # base64 needs padding
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        claims: dict[str, Any] = json.loads(payload)
        client_id = claims.get("client_id")
        return client_id if isinstance(client_id, str) else None
    except Exception:
        return None


def step2_exchange_di_token(ticket: str) -> dict:
    """POST diauth.garmin.com/di-oauth2-service/oauth/token with the ticket.
    Try each DI clientId. Return {di_token, di_refresh_token, di_client_id}."""
    from curl_cffi import requests as cf_requests

    print("[2/2] Exchanging serviceTicket → DI token via diauth.garmin.com...")

    last_err = None
    for client_id in DI_CLIENT_IDS:
        print(f"      try clientId={client_id}")
        basic_auth = "Basic " + base64.b64encode(f"{client_id}:".encode()).decode()
        headers = {
            "User-Agent": NATIVE_API_USER_AGENT,
            "X-Garmin-User-Agent": NATIVE_API_USER_AGENT,
            "X-Garmin-Paired-App-Version": "10861",
            "X-Garmin-Client-Platform": "Android",
            "X-App-Ver": "10861",
            "X-Lang": "en",
            "Authorization": basic_auth,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
        }
        data = {
            "client_id": client_id,
            "service_ticket": ticket,
            "grant_type": DI_GRANT_TYPE,
            "service_url": MOBILE_SSO_SERVICE_URL,
        }
        try:
            resp = cf_requests.post(
                DI_TOKEN_URL,
                impersonate="chrome",
                headers=headers,
                data=data,
                timeout=30,
            )
        except Exception as e:
            last_err = f"{client_id}: network error {type(e).__name__}: {e}"
            print(f"        → {last_err}")
            continue

        print(f"        → HTTP {resp.status_code}")
        if resp.status_code == 429:
            raise RuntimeError(
                f"429 from diauth.garmin.com on {client_id}. Cloudflare rate-limit on "
                "this endpoint. Strategy: wait 1h+, do not retry tightly."
            )
        if not resp.ok:
            last_err = f"{client_id}: HTTP {resp.status_code} {resp.text[:200]}"
            continue

        try:
            payload = resp.json()
            di_token = payload["access_token"]
            di_refresh = payload.get("refresh_token")
            di_client_id = _extract_client_id_from_jwt(di_token) or client_id
            print(
                f"[2/2] ✅ DI token received ({di_token[:20]}..., "
                f"refresh={'yes' if di_refresh else 'no'}, jwt_client_id={di_client_id})"
            )
            return {
                "di_token": di_token,
                "di_refresh_token": di_refresh,
                "di_client_id": di_client_id,
            }
        except Exception as e:
            last_err = f"{client_id}: parse error {e}"
            continue

    raise RuntimeError(f"DI token exchange failed for all client IDs. Last error: {last_err}")


def write_token_file(tokens: dict) -> None:
    GARTH_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens), encoding="utf-8")
    print(f"\n[ok] Token written to {TOKEN_FILE} ({TOKEN_FILE.stat().st_size} bytes)")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Garmin SSO via SeleniumBase UC")
    parser.add_argument("--email", help="Garmin email (overrides $GARMIN_EMAIL)")
    parser.add_argument("--password", help="Garmin password (overrides $GARMIN_PASSWORD)")
    args = parser.parse_args()

    try:
        import curl_cffi  # noqa: F401
        import seleniumbase  # noqa: F401
    except ImportError as exc:
        print(
            f"ERROR: missing optional dependency ({exc.name}). "
            "Install the recovery extra first: uv sync --extra reauth",
            file=sys.stderr,
        )
        return 2

    email = args.email or os.environ.get("GARMIN_EMAIL")
    password = args.password or os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        print(
            "ERROR: email + password required (--email/--password or env vars).",
            file=sys.stderr,
        )
        return 2

    print("=== Garmin SSO via SeleniumBase UC + DI exchange ===")
    print(f"Account: {email}")
    print(f"Target: {TOKEN_FILE}\n")

    # Clean up old garth-format files if present (avoids confusion)
    for old in (GARTH_DIR / "oauth1_token.json", GARTH_DIR / "oauth2_token.json"):
        if old.exists():
            old.unlink()
            print(f"[cleanup] removed obsolete {old.name} (garth-only format)")

    try:
        ticket = step1_get_ticket_via_chrome(email, password)
        tokens = step2_exchange_di_token(ticket)
        write_token_file(tokens)
        print("\nDONE - verify with: uv run python scripts/smoke_mcp.py")
        return 0
    except KeyboardInterrupt:
        print("\n[abort] interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
