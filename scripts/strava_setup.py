"""One-time Strava OAuth setup.

Prerequisites:
  1. Create a Strava API app at https://www.strava.com/settings/api
     - Authorization Callback Domain: localhost
  2. Set env vars STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET (the values from
     your Strava app page).

What this script does:
  - Starts a tiny HTTP listener on http://localhost:8765
  - Opens your browser to Strava's authorization page
  - Catches the redirect, exchanges the code for tokens
  - Saves tokens to ~/.open-coach/strava_tokens.json
  - The MCP server will read & auto-refresh from there afterwards.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from open_coach.paths import migrate_legacy_data_dir
from open_coach.strava_auth import DEFAULT_TOKEN_FILE, TOKEN_URL, save_tokens

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"
SCOPES = "read,activity:read_all,profile:read_all"


_received: dict[str, str] = {}
_expected_state: str = ""


class _CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # silence default access log
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        if "error" in params:
            _received["error"] = params["error"][0]
            self._reply("Strava auth refused. You can close this tab.", 400)
            return
        if "code" not in params:
            self._reply("Missing 'code' in callback.", 400)
            return
        state = params.get("state", [""])[0]
        if state != _expected_state:
            _received["error"] = "state_mismatch"
            self._reply(
                "CSRF check failed: 'state' does not match. Close this tab and re-run the script.",
                400,
            )
            return
        _received["code"] = params["code"][0]
        _received["scope"] = params.get("scope", [""])[0]
        self._reply("Strava authorized. You can close this tab.", 200)

    def _reply(self, msg: str, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())


def main() -> int:
    migrate_legacy_data_dir()  # tokens go to the renamed ~/.open-coach/
    client_id = os.environ.get("STRAVA_CLIENT_ID", "")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print(
            "ERROR: set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET first.\n"
            "  Windows PowerShell:\n"
            '    setx STRAVA_CLIENT_ID "..."\n'
            '    setx STRAVA_CLIENT_SECRET "..."\n'
            "  (open a new shell after setx so the vars are visible.)",
            file=sys.stderr,
        )
        return 2

    global _expected_state
    _expected_state = secrets.token_urlsafe(16)

    auth_url = "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "approval_prompt": "auto",
            "scope": SCOPES,
            "state": _expected_state,
        }
    )

    print(f"Opening browser for Strava auth -> {auth_url}")
    print(f"Listening on {REDIRECT_URI} for the callback…")
    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _CallbackHandler)
    webbrowser.open(auth_url)

    while "code" not in _received and "error" not in _received:
        server.handle_request()

    if "error" in _received:
        if _received["error"] == "state_mismatch":
            print(
                "ERROR: CSRF 'state' mismatch on callback - the request did not "
                "come from the auth flow started by this script. Aborting.",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: Strava returned '{_received['error']}'", file=sys.stderr)
        return 3

    code = _received["code"]
    print("Got authorization code, exchanging for tokens…")

    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))

    out = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at": tokens["expires_at"],
        "athlete_id": (tokens.get("athlete") or {}).get("id"),
        "scope": _received.get("scope", SCOPES),
    }
    save_tokens(out, DEFAULT_TOKEN_FILE)
    print(f"[ok] tokens saved to {DEFAULT_TOKEN_FILE}")
    print(f"[ok] athlete id: {out['athlete_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
