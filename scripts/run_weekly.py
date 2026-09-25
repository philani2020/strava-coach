"""Entry point for the weekly job.

    python scripts/run_weekly.py            # the real thing
    python scripts/run_weekly.py --demo     # fake data, no credentials needed
    python scripts/run_weekly.py --force    # rewrite this week's review
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import timedelta
from pathlib import Path

import analyze
import coach
import render

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
HISTORY_PATH = ROOT / "data" / "history.json"
PAGE_PATH = ROOT / "docs" / "index.html"

HISTORY_WEEKS = 12


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit("config.json is missing. Copy config.example.json across.")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def demo_activities(tz_name: str) -> list[dict]:
    """Plausible fake weeks so you can see the page before wiring up Strava."""
    random.seed(7)
    start, _ = analyze.last_complete_week(tz_name)
    activities = []

    for week_back in range(HISTORY_WEEKS):
        monday = start - timedelta(weeks=week_back)
        base = 9.5 - week_back * 0.35
        for day in (0, 2, 4, 6):
            if random.random() < 0.15:
                continue
            distance = max(4.0, random.gauss(base, 2.2)) * 1000
            pace = random.uniform(300, 355)
            activities.append({
                "name": random.choice(["Morning run", "Easy shakeout", "Tempo",
                                       "Long run", "Parkrun", "Evening km"]),
                "sport_type": "Run",
                "start_date_local": (monday + timedelta(days=day, hours=6)).isoformat(),
                "distance": round(distance),
                "moving_time": round(distance / 1000 * pace),
                "total_elevation_gain": round(random.uniform(20, 160)),
                "average_heartrate": round(random.uniform(132, 172)),
            })
        for day in (1, 3):
            if random.random() < 0.25:
                continue
            activities.append({
                "name": random.choice(["Upper body", "Legs", "Full body", "Push day"]),
                "sport_type": "WeightTraining",
                "start_date_local": (monday + timedelta(days=day, hours=18)).isoformat(),
                "distance": 0,
                "moving_time": round(random.uniform(2400, 4200)),
                "total_elevation_gain": 0,
            })

    activities.sort(key=lambda a: a["start_date_local"])
    return activities


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="use generated sample data")
    parser.add_argument("--force", action="store_true", help="regenerate the latest review")
    args = parser.parse_args()

    config = load_config()
    tz_name = config.get("timezone", "Africa/Johannesburg")

    if args.demo:
        print("Demo mode: no Strava call.")
        activities = demo_activities(tz_name)
    else:
        import strava_client

        token = strava_client.refresh_access_token()
        window_start, _ = analyze.last_complete_week(tz_name)
        after = window_start - timedelta(weeks=HISTORY_WEEKS)
        _, window_end = analyze.last_complete_week(tz_name)
        activities = strava_client.fetch_activities(
            token,
            after_epoch=int(after.timestamp()),
            before_epoch=int((window_end + timedelta(days=1)).timestamp()),
        )

    history = analyze.build_history(activities, HISTORY_WEEKS, config, tz_name)
    stored = render.load_history(HISTORY_PATH)
    reviews: dict = stored.get("reviews", {})

    latest = history[-1]
    print(f"Week {latest['week_id']}: {latest['run_distance_km']:g} km, "
          f"{latest['run_count']} runs, {latest['gym_count']} gym, flags={latest['flags']}")

    if latest["week_id"] in reviews and not args.force:
        print("Review already written for this week. Pass --force to redo it.")
    else:
        previous_id = history[-2]["week_id"] if len(history) > 1 else None
        previous_review = reviews.get(previous_id) if previous_id else None
        if args.demo and not _has_llm_key():
            reviews[latest["week_id"]] = coach.fallback_note(latest, config)
        else:
            reviews[latest["week_id"]] = coach.write_review(
                latest, history, config, previous_review
            )
        print(f"Review written by {reviews[latest['week_id']]['generated_by']}.")

    render.save_history(history, reviews, HISTORY_PATH)
    render.render(history, reviews, config, PAGE_PATH)


def _has_llm_key() -> bool:
    import os

    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))


if __name__ == "__main__":
    main()
