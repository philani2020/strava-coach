"""Turns raw Strava activities into weekly training summaries.

Everything the coach says is grounded in the numbers produced here, so this
module does the arithmetic and the language model only does the talking.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
GYM_TYPES = {
    "WeightTraining",
    "Workout",
    "Crossfit",
    "HighIntensityIntervalTraining",
    "Yoga",
    "Pilates",
}


def classify(activity: dict) -> str:
    sport = activity.get("sport_type") or activity.get("type") or ""
    if sport in RUN_TYPES:
        return "run"
    if sport in GYM_TYPES:
        return "gym"
    return "other"


def local_start(activity: dict) -> datetime:
    """Strava's start_date_local is the wall-clock time where you trained.

    Strava suffixes it with a misleading "Z", so any offset is dropped and the
    result is always naive local time.
    """
    raw = activity.get("start_date_local", "").replace("Z", "")
    return datetime.fromisoformat(raw).replace(tzinfo=None)


def last_complete_week(tz_name: str, today: datetime | None = None) -> tuple[datetime, datetime]:
    """Monday 00:00 to Sunday 23:59:59 of the week that just finished."""
    tz = ZoneInfo(tz_name)
    now = today or datetime.now(tz)
    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = this_monday - timedelta(days=7)
    end = this_monday - timedelta(seconds=1)
    return start, end


def activity_load(activity: dict, max_hr: int) -> float:
    """A single effort number per session.

    Strava's Relative Effort (suffer_score) is used when available because it
    already accounts for heart rate. Otherwise we approximate: duration scaled
    by how hard the heart was working, with a flat multiplier for gym work
    where heart rate is a poor proxy for the actual stress.
    """
    if activity.get("suffer_score"):
        return float(activity["suffer_score"])

    minutes = activity.get("moving_time", 0) / 60
    kind = classify(activity)
    avg_hr = activity.get("average_heartrate")

    if avg_hr and max_hr:
        intensity = max(0.4, min(1.0, avg_hr / max_hr))
        return round(minutes * (intensity**2) * 2.2, 1)

    multiplier = {"run": 1.0, "gym": 0.55}.get(kind, 0.7)
    return round(minutes * multiplier, 1)


def _pace_str(seconds_per_km: float | None) -> str | None:
    if not seconds_per_km or seconds_per_km <= 0:
        return None
    minutes, seconds = divmod(int(round(seconds_per_km)), 60)
    return f"{minutes}:{seconds:02d}"


def summarise_week(
    activities: list[dict], start: datetime, end: datetime, config: dict
) -> dict:
    """Build the full metric set for one Monday-to-Sunday block."""
    max_hr = config.get("max_heart_rate") or 0
    wall_start, wall_end = start.replace(tzinfo=None), end.replace(tzinfo=None)
    in_week = [a for a in activities if wall_start <= local_start(a) <= wall_end]

    runs = [a for a in in_week if classify(a) == "run"]
    gym = [a for a in in_week if classify(a) == "gym"]
    other = [a for a in in_week if classify(a) == "other"]

    run_metres = sum(a.get("distance", 0) for a in runs)
    run_seconds = sum(a.get("moving_time", 0) for a in runs)
    gym_seconds = sum(a.get("moving_time", 0) for a in gym)

    avg_pace = run_seconds / (run_metres / 1000) if run_metres > 100 else None

    longest = max(runs, key=lambda a: a.get("distance", 0), default=None)

    # Day-by-day shape of the week, which is what the page leads with.
    days = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        day_acts = [a for a in in_week if local_start(a).date() == day.date()]
        day_load = sum(activity_load(a, max_hr) for a in day_acts)
        kinds = {classify(a) for a in day_acts}
        days.append(
            {
                "date": day.date().isoformat(),
                "weekday": day.strftime("%a"),
                "load": round(day_load, 1),
                "kind": "run" if "run" in kinds else ("gym" if "gym" in kinds else
                        ("other" if kinds else "rest")),
                "distance_km": round(
                    sum(a.get("distance", 0) for a in day_acts if classify(a) == "run") / 1000, 1
                ),
                "sessions": [
                    {
                        "name": a.get("name", "Untitled"),
                        "kind": classify(a),
                        "distance_km": round(a.get("distance", 0) / 1000, 2),
                        "minutes": round(a.get("moving_time", 0) / 60),
                        "avg_hr": a.get("average_heartrate"),
                        "pace": _pace_str(
                            a["moving_time"] / (a["distance"] / 1000)
                            if a.get("distance", 0) > 100 else None
                        ),
                    }
                    for a in day_acts
                ],
            }
        )

    # Easy versus hard, using heart rate where Strava has it.
    easy = hard = unknown = 0
    for run in runs:
        avg_hr = run.get("average_heartrate")
        if avg_hr and max_hr:
            if avg_hr / max_hr < config.get("easy_hr_ceiling", 0.78):
                easy += 1
            else:
                hard += 1
        else:
            unknown += 1

    trained_days = sum(1 for d in days if d["kind"] != "rest")
    gaps, run_length = [], 0
    for day in days:
        if day["kind"] == "rest":
            run_length += 1
        else:
            gaps.append(run_length)
            run_length = 0
    gaps.append(run_length)

    return {
        "week_id": f"{start.isocalendar().year}-W{start.isocalendar().week:02d}",
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "label": f"{start.day}\u2013{end.day} {end.strftime('%B')}",
        "run_count": len(runs),
        "run_distance_km": round(run_metres / 1000, 1),
        "run_time_min": round(run_seconds / 60),
        "run_elevation_m": round(sum(a.get("total_elevation_gain", 0) for a in runs)),
        "avg_pace": _pace_str(avg_pace),
        "longest_run_km": round(longest.get("distance", 0) / 1000, 1) if longest else 0,
        "longest_run_name": longest.get("name") if longest else None,
        "gym_count": len(gym),
        "gym_time_min": round(gym_seconds / 60),
        "other_count": len(other),
        "total_time_min": round(
            sum(a.get("moving_time", 0) for a in in_week) / 60
        ),
        "load": round(sum(activity_load(a, max_hr) for a in in_week), 1),
        "easy_runs": easy,
        "hard_runs": hard,
        "unclassified_runs": unknown,
        "trained_days": trained_days,
        "longest_rest_streak": max(gaps),
        "days": days,
    }


def add_trends(week: dict, previous: list[dict]) -> dict:
    """Compare a week against the four before it."""
    recent = previous[-4:]

    def mean_of(key: str) -> float:
        values = [w[key] for w in recent if w.get(key) is not None]
        return statistics.fmean(values) if values else 0.0

    chronic_load = mean_of("load")
    baseline_km = mean_of("run_distance_km")

    week["chronic_load"] = round(chronic_load, 1)
    week["acwr"] = round(week["load"] / chronic_load, 2) if chronic_load > 0 else None
    week["distance_change_pct"] = (
        round((week["run_distance_km"] - baseline_km) / baseline_km * 100)
        if baseline_km > 0 else None
    )
    week["baseline_distance_km"] = round(baseline_km, 1)

    flags = []
    if week["acwr"] and week["acwr"] > 1.5:
        flags.append("load_spike")
    if week["acwr"] and week["acwr"] < 0.7 and chronic_load > 0:
        flags.append("load_drop")
    if week["distance_change_pct"] is not None and week["distance_change_pct"] > 25:
        flags.append("mileage_jump")
    if week["run_count"] >= 3 and week["hard_runs"] > week["easy_runs"]:
        flags.append("too_much_intensity")
    if week["gym_count"] == 0 and any(w["gym_count"] > 0 for w in recent):
        flags.append("gym_skipped")
    if week["trained_days"] == 0:
        flags.append("no_training")
    week["flags"] = flags

    return week


def build_history(activities: list[dict], weeks: int, config: dict, tz_name: str) -> list[dict]:
    """Summarise the last N complete weeks, oldest first, with trends attached."""
    latest_start, latest_end = last_complete_week(tz_name)
    summaries: list[dict] = []

    for index in range(weeks - 1, -1, -1):
        start = latest_start - timedelta(weeks=index)
        end = latest_end - timedelta(weeks=index)
        summaries.append(summarise_week(activities, start, end, config))

    for position, week in enumerate(summaries):
        add_trends(week, summaries[:position])

    return summaries
