"""Writes the weekly review as an argument between two coaches.

The numbers come from analyze.py. Everything factual - the headline, what went
well, what's worth watching - is computed here in code, so the coaches are only
ever writing opinion about facts they cannot bend.

How the exchange works:
  One coach opens on the week's numbers. The other reads what they just wrote
  and answers it, then gives their own advice for the coming week. Who opens
  alternates from week to week, and both of them can see last week's exchange,
  so the argument carries instead of resetting every Monday.
"""

from __future__ import annotations

import json
import os
import re

import requests

TIMEOUT = 90

COACHES = {
    "snark": {
        "default_name": "Coach Dunkley",
        "persona": (
            "You are a veteran coach who has seen thirty years of athletes and has "
            "never once been impressed. You look at a training week and find the "
            "least flattering number in it, then build your whole remark around that. "
            "Faint praise is the most you will offer, and you undercut it immediately. "
            "Clipped, precise, entirely unmoved.\n"
            "Hard limits: your contempt is aimed at the training, never at the athlete "
            "as a person. Say nothing about their body, weight, appearance or worth. "
            "Never suggest they should stop, never imply they are wasting their time, "
            "and never push them towards more volume in a way a reasonable person "
            "would actually act on if they were tired or hurt. This is a bit, and the "
            "athlete is in on it."
        ),
    },
    "kind": {
        "default_name": "Coach Amari",
        "persona": (
            "You are the other coach at the club and you cannot stand how your "
            "colleague talks to people. You have just read their assessment of this "
            "athlete's week and you are quietly furious about it. Push back on the "
            "specific thing they said, then point out what they deliberately ignored. "
            "Warm towards the athlete, pointed towards your colleague. You are not "
            "saccharine and you do not flatter - you are simply accurate about what "
            "actually went well."
        ),
    },
}

SHARED_RULES = """
You are writing one part of a weekly training review that the athlete reads on a
web page every Monday.

Rules:
- Three or four sentences. No more.
- Use their real numbers. Never invent a detail that is not in the data.
- Cover how the week went. Your advice for next week goes in a separate field.
- Do not greet or sign off. Your name is added for you.
- No emoji, no hashtags.
- A quiet or empty week is not a failure. If they barely trained, the useful
  response is helping them restart, not scolding them. This applies to both of
  you, including the unimpressed one.
- If the data suggests a possible injury, suggest a physiotherapist rather than
  guessing at a diagnosis.

Return ONLY a JSON object with exactly these keys:
  "comment": string, your read on the week
  "tip": string, one specific thing they should do next week, in your voice
"""


def coach_name(role: str, config: dict) -> str:
    configured = config.get("coaches", {}).get(role)
    return configured or COACHES[role]["default_name"]


def _compact_week(week: dict) -> dict:
    keep = (
        "week_id", "label", "run_count", "run_distance_km", "run_time_min",
        "run_elevation_m", "avg_pace", "longest_run_km", "gym_count",
        "gym_time_min", "total_time_min", "load", "easy_runs", "hard_runs",
        "trained_days", "longest_rest_streak", "acwr", "distance_change_pct",
        "baseline_distance_km", "flags",
    )
    return {k: week[k] for k in keep if k in week}


def _week_payload(week: dict, history: list[dict], config: dict) -> dict:
    return {
        "athlete_goals": config.get("goals", {}),
        "week_just_finished": _compact_week(week),
        "daily_breakdown": [
            {
                "day": d["weekday"],
                "kind": d["kind"],
                "distance_km": d["distance_km"],
                "sessions": [s["name"] for s in d["sessions"]],
            }
            for d in week["days"]
        ],
        "previous_four_weeks": [_compact_week(w) for w in history[-5:-1]],
    }


def _call(system: str, user: str) -> str:
    provider = (os.environ.get("LLM_PROVIDER") or "gemini").lower()

    if provider == "groq":
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            json={
                "model": os.environ.get("LLM_MODEL") or "llama-3.3-70b-versatile",
                "temperature": 0.9,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    model = os.environ.get("LLM_MODEL") or "gemini-flash-latest"
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"},
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]


def _parse(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    if "comment" not in data or "tip" not in data:
        raise ValueError("Coach response is missing 'comment' or 'tip'")
    return data


def _speak(
    role: str,
    week: dict,
    history: list[dict],
    config: dict,
    opponent_said: dict | None,
    last_exchange: list[dict] | None,
) -> dict:
    """One coach's turn."""
    me = coach_name(role, config)
    them = coach_name("kind" if role == "snark" else "snark", config)

    system = (
        f"{COACHES[role]['persona']}\n{SHARED_RULES}\n"
        f"You are {me}. Your colleague is {them}."
    )

    user = "The athlete's week, as JSON:\n" + json.dumps(
        _week_payload(week, history, config), indent=2
    )

    if last_exchange:
        previous = "\n".join(f"{turn['name']}: {turn['comment']}" for turn in last_exchange)
        user += f"\n\nLast Monday the two of you said:\n{previous}"

    if opponent_said:
        user += (
            f"\n\n{them} has just written this about the week:\n"
            f"\"{opponent_said['comment']}\"\n"
            f"Their advice for next week: \"{opponent_said['tip']}\"\n\n"
            "Answer them directly as well as reading the week yourself."
        )
    else:
        user += "\n\nYou are going first this week."

    return _parse(_call(system, user))


# ---------------------------------------------------------------- facts

def build_headline(week: dict) -> str:
    if week["trained_days"] == 0:
        return "A week off"
    parts = [f"{week['run_distance_km']:g} km"] if week["run_distance_km"] else []
    if week["gym_count"]:
        parts.append(f"{week['gym_count']} gym")
    parts.append(f"{week['trained_days']} of 7 days")
    return ", ".join(parts)


def build_went_well(week: dict, config: dict) -> list[str]:
    goal = config.get("goals", {}).get("weekly_distance_km")
    out = []
    if week["trained_days"] >= 4:
        out.append(f"Trained on {week['trained_days']} days")
    if week["gym_count"] >= 2:
        out.append(f"{week['gym_count']} strength sessions in the bank")
    if goal and week["run_distance_km"] >= goal:
        out.append(f"Cleared your {goal} km target")
    if week["longest_run_km"] >= 10:
        out.append(f"Longest run of {week['longest_run_km']:g} km")
    if week["easy_runs"] > week["hard_runs"] and week["run_count"] >= 3:
        out.append("Most of the running kept easy")
    return out


def build_watch_out(week: dict) -> list[str]:
    out = []
    if "load_spike" in week["flags"]:
        out.append("Training load jumped sharply on your recent average")
    if "mileage_jump" in week["flags"]:
        out.append(f"Distance up {week['distance_change_pct']}% on your four-week norm")
    if "too_much_intensity" in week["flags"]:
        out.append("More hard runs than easy ones")
    if "gym_skipped" in week["flags"]:
        out.append("No strength work this week")
    if week["longest_rest_streak"] >= 4:
        out.append(f"A {week['longest_rest_streak']}-day gap between sessions")
    return out


# ---------------------------------------------------------------- fallback

def fallback_exchange(week: dict, config: dict, opener: str) -> dict:
    """Scripted stand-in when the model is unreachable. Still grounded in the data."""
    km = week["run_distance_km"]
    days = week["trained_days"]

    if days == 0:
        snark = (
            "Nothing logged. I have no numbers to be unimpressed by, which is itself "
            "a kind of result."
        )
        kind = (
            "Nothing logged means life happened, which it does. One easy run this "
            "week, short enough that finishing it is never in doubt, and the habit is "
            "back."
        )
    else:
        snark = (
            f"{km:g} km across {days} of seven days, {week['total_time_min']} minutes "
            "of moving time. It is training. I would not call it a campaign."
        )
        kind = (
            f"He has once again said nothing about the {week['gym_count']} strength "
            f"session(s) or the {week['longest_run_km']:g} km long run. "
            f"{days} days out of seven while holding down a life is the part that "
            "actually compounds."
        )

    turns = {
        "snark": {"comment": snark, "tip": "Add nothing. Repeat this week without the excuses."},
        "kind": {
            "comment": kind,
            "tip": "Keep next week's easy runs conversational and protect two gym slots.",
        },
    }

    order = [opener, "kind" if opener == "snark" else "snark"]
    return {
        "exchange": [
            {
                "role": role,
                "name": coach_name(role, config),
                "comment": turns[role]["comment"],
            }
            for role in order
        ],
        "next_week": [
            {"role": role, "name": coach_name(role, config), "text": turns[role]["tip"]}
            for role in order
        ],
        "generated_by": "fallback",
    }


# ---------------------------------------------------------------- entry point

def write_review(
    week: dict,
    history: list[dict],
    config: dict,
    previous_review: dict | None,
) -> dict:
    """Produce the full week review, exchange included."""
    # Alternate who opens; whoever opened last week goes second this week.
    last_opener = (previous_review or {}).get("opener")
    opener = "kind" if last_opener == "snark" else "snark"
    responder = "kind" if opener == "snark" else "snark"

    last_exchange = (previous_review or {}).get("exchange")

    review = {
        "headline": build_headline(week),
        "went_well": build_went_well(week, config),
        "watch_out": build_watch_out(week),
        "opener": opener,
    }

    try:
        first = _speak(opener, week, history, config, None, last_exchange)
        second = _speak(responder, week, history, config, first, last_exchange)

        review["exchange"] = [
            {"role": opener, "name": coach_name(opener, config),
             "comment": first["comment"]},
            {"role": responder, "name": coach_name(responder, config),
             "comment": second["comment"]},
        ]
        review["next_week"] = [
            {"role": opener, "name": coach_name(opener, config), "text": first["tip"]},
            {"role": responder, "name": coach_name(responder, config), "text": second["tip"]},
        ]
        review["generated_by"] = (
            f"{os.environ.get('LLM_PROVIDER', 'gemini')}:"
            f"{os.environ.get('LLM_MODEL') or 'default'}"
        )
    except Exception as error:  # noqa: BLE001 - the page must render regardless
        print(f"Coaching model unavailable ({type(error).__name__}: {error}). Using fallback.")
        review.update(fallback_exchange(week, config, opener))

    return review


# Kept so run_weekly.py's demo path works with no API key present.
def fallback_note(week: dict, config: dict) -> dict:
    review = {
        "headline": build_headline(week),
        "went_well": build_went_well(week, config),
        "watch_out": build_watch_out(week),
        "opener": "snark",
    }
    review.update(fallback_exchange(week, config, "snark"))
    return review
