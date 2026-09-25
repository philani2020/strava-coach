"""Strava API access: refreshes the access token, then pulls activities.

Strava access tokens live for 6 hours, so we never store one. We store the
refresh token and mint a fresh access token on every run. Strava sometimes
rotates the refresh token as well; if that happens and a GitHub token is
available, we write the new one back into the repo secret so the job doesn't
quietly die a few weeks from now.
"""

from __future__ import annotations

import base64
import os
import sys
import time

import requests

TOKEN_URL = "https://www.strava.com/oauth/token"
API_BASE = "https://www.strava.com/api/v3"
TIMEOUT = 30


class StravaError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise StravaError(
            f"Missing {name}. Add it under Settings > Secrets and variables > Actions."
        )
    return value


def refresh_access_token() -> str:
    """Trade the stored refresh token for a usable access token."""
    client_id = _require("STRAVA_CLIENT_ID")
    client_secret = _require("STRAVA_CLIENT_SECRET")
    refresh_token = _require("STRAVA_REFRESH_TOKEN")

    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=TIMEOUT,
    )

    if response.status_code == 400:
        raise StravaError(
            "Strava rejected the refresh token. It was most likely revoked, or the "
            "client ID and secret belong to a different app. Re-run "
            "scripts/get_refresh_token.py to mint a new one."
        )
    response.raise_for_status()
    payload = response.json()

    returned = payload.get("refresh_token")
    if returned and returned != refresh_token:
        print("Strava rotated the refresh token.")
        _persist_refresh_token(returned)

    return payload["access_token"]


def _persist_refresh_token(new_token: str) -> None:
    """Write a rotated refresh token back into the GitHub Actions secret.

    Needs a fine-grained PAT with 'Secrets: read and write' on this repo,
    stored as GH_PAT. Without it we just warn loudly.
    """
    gh_token = os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()

    if not gh_token or not repo:
        print(
            "WARNING: the refresh token changed but GH_PAT is not set, so it could "
            "not be saved. Update the STRAVA_REFRESH_TOKEN secret by hand with the "
            "value printed below, or future runs will fail.\n"
            f"New refresh token: {new_token}",
            file=sys.stderr,
        )
        return

    try:
        from nacl import encoding, public
    except ImportError:
        print("WARNING: PyNaCl is not installed, cannot update the secret.", file=sys.stderr)
        return

    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    key_url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    key = requests.get(key_url, headers=headers, timeout=TIMEOUT)
    key.raise_for_status()
    key = key.json()

    sealed = public.SealedBox(
        public.PublicKey(key["key"].encode("utf-8"), encoding.Base64Encoder())
    ).encrypt(new_token.encode("utf-8"))

    put = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/STRAVA_REFRESH_TOKEN",
        headers=headers,
        json={
            "encrypted_value": base64.b64encode(sealed).decode("utf-8"),
            "key_id": key["key_id"],
        },
        timeout=TIMEOUT,
    )
    put.raise_for_status()
    print("Saved the rotated refresh token back to repository secrets.")


def fetch_activities(access_token: str, after_epoch: int, before_epoch: int) -> list[dict]:
    """Page through the athlete's activities in a time window (oldest first)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    activities: list[dict] = []
    page = 1

    while True:
        response = requests.get(
            f"{API_BASE}/athlete/activities",
            headers=headers,
            params={
                "after": after_epoch,
                "before": before_epoch,
                "per_page": 200,
                "page": page,
            },
            timeout=TIMEOUT,
        )

        if response.status_code == 429:
            reset = int(response.headers.get("X-RateLimit-Reset", 900))
            wait = min(max(reset, 60), 900)
            print(f"Hit the Strava rate limit, waiting {wait}s.")
            time.sleep(wait)
            continue

        if response.status_code in (401, 403):
            raise StravaError(
                "Strava refused to list activities, so the refresh token lacks the "
                "activity:read_all scope. The token shown on strava.com/settings/api "
                "only has 'read'. Run scripts/get_refresh_token.py, tick the "
                "activities boxes, and update STRAVA_REFRESH_TOKEN."
            )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break

        activities.extend(batch)
        if len(batch) < 200:
            break
        page += 1

    activities.sort(key=lambda a: a.get("start_date_local", ""))
    print(f"Fetched {len(activities)} activities from Strava.")
    return activities
