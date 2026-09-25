"""Run this once on your own machine to get a Strava refresh token.

    python scripts/get_refresh_token.py

It opens Strava's consent page, catches the redirect on localhost, swaps the
code for tokens and prints the refresh token. Copy that into the
STRAVA_REFRESH_TOKEN repository secret. You should not need to run it again.

Before running, your Strava app (https://www.strava.com/settings/api) must have
"Authorization Callback Domain" set to exactly: localhost
"""

from __future__ import annotations

import http.server
import threading
import urllib.parse
import webbrowser

import requests

PORT = 8721
REDIRECT_URI = f"http://localhost:{PORT}/exchange"

# activity:read_all - see your activities, including private ones
# profile:read_all  - your athlete profile
# This app only ever reads. It never edits anything on Strava, so it does not
# ask for activity:write.
SCOPE = "activity:read_all,profile:read_all"

received_code: str | None = None
granted_scope = ""


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        global received_code, granted_scope
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if "code" in params:
            received_code = params["code"][0]
            granted = params.get("scope", [""])[0]
            granted_scope = granted
            body = "Authorised. You can close this tab and return to the terminal."
            if "activity:read_all" not in granted:
                body = (
                    "Warning: you did not tick the private activities box, so private "
                    "activities will be skipped. Re-run the script to try again."
                )
        else:
            body = f"Something went wrong: {params.get('error', ['unknown'])[0]}"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<!doctype html><meta charset=utf-8><p>{body}</p>".encode())

    def log_message(self, *args):
        pass


def main() -> None:
    client_id = input("Strava Client ID: ").strip()
    client_secret = input("Strava Client Secret: ").strip()

    auth_url = "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "approval_prompt": "force",
            "scope": SCOPE,
        }
    )

    server = http.server.HTTPServer(("localhost", PORT), CallbackHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"\nOpening Strava in your browser. If nothing happens, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    while received_code is None:
        server.handle_request()
    server.shutdown()

    tokens = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": received_code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if tokens.status_code in (400, 401):
        raise SystemExit(
            f"\nStrava refused the code exchange ({tokens.status_code}): {tokens.text[:300]}\n"
            "This almost always means the Client Secret doesn't match the Client ID. "
            "Copy the Client Secret (click 'Show') from https://www.strava.com/settings/api, "
            "not 'Your Access Token' or 'Your Refresh Token'."
        )
    tokens.raise_for_status()
    tokens = tokens.json()

    print("\nDone. Add these three as repository secrets:\n")
    print(f"  STRAVA_CLIENT_ID      {client_id}")
    print(f"  STRAVA_CLIENT_SECRET  {client_secret}")
    print(f"  STRAVA_REFRESH_TOKEN  {tokens['refresh_token']}")
    print(f"\nScopes granted: {granted_scope or '(none reported)'}")
    if "activity:read_all" not in granted_scope:
        print("WARNING: activity:read_all was NOT granted, so the weekly job will "
              "get 403. Re-run and tick every box on the Strava page.")
    print(f"\nAthlete: {tokens.get('athlete', {}).get('firstname', 'unknown')}")


if __name__ == "__main__":
    main()
