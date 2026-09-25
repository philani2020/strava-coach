"""Renders the report into docs/index.html for GitHub Pages.

Design notes, so future edits stay coherent:
  The hero is the shape of the week - seven bars, one per day, height by training
  load, coloured by what you did. Colour carries data and nothing else: pine for
  running, rust for lifting, ash for rest. Citron appears exactly once, on the
  single number that defined the week.
  Numbers are set in Archivo with tabular figures. The coach's note is set in
  Newsreader, because it should read like a letter rather than a dashboard.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KIND_COLOUR = {"run": "run", "gym": "lift", "other": "ash", "rest": "rest"}


def e(value) -> str:
    return html.escape(str(value), quote=True)


def _bars(days: list[dict]) -> str:
    peak = max([d["load"] for d in days] + [1])
    cells = []
    for index, day in enumerate(days):
        height = max(2, round(day["load"] / peak * 100)) if day["load"] else 2
        kind = KIND_COLOUR.get(day["kind"], "rest")
        detail = ", ".join(s["name"] for s in day["sessions"]) or "Rest"
        minutes = sum(s["minutes"] for s in day["sessions"])
        if day["distance_km"]:
            value = f"{day['distance_km']:g} km"
        elif minutes:
            value = f"{minutes}m"
        else:
            value = ""
        cells.append(
            f'<div class="day" style="--i:{index}">'
            f'<div class="track"><div class="bar {kind}" style="--h:{height}%" '
            f'title="{e(detail)}"></div></div>'
            f'<div class="dayname">{e(day["weekday"])}</div>'
            f'<div class="dayval">{e(value)}</div>'
            f"</div>"
        )
    return "".join(cells)


def _list(items: list[str], kind: str) -> str:
    if not items:
        return ""
    rows = "".join(f'<li class="{kind}">{e(item)}</li>' for item in items)
    return f'<ul class="marks">{rows}</ul>'


def _exchange(turns: list[dict]) -> str:
    """The two coaches, in the order they spoke."""
    if not turns:
        return ""
    blocks = []
    for turn in turns:
        role = "snark" if turn.get("role") == "snark" else "kind"
        blocks.append(
            f'<div class="turn {role}">'
            f'<p class="who">{e(turn["name"])}</p>'
            f'<p class="said">{e(turn["comment"])}</p>'
            f"</div>"
        )
    return f'<div class="exchange">{"".join(blocks)}</div>'


def _tips(items: list) -> str:
    """next_week entries, each attributed to whichever coach insisted on it."""
    if not items:
        return ""
    rows = []
    for item in items:
        if isinstance(item, str):
            rows.append(f'<li class="next">{e(item)}</li>')
            continue
        role = "snark" if item.get("role") == "snark" else "kind"
        rows.append(
            f'<li class="tip {role}"><span class="from">{e(item["name"])}</span>'
            f'<span class="advice">{e(item["text"])}</span></li>'
        )
    return f'<ul class="tips">{"".join(rows)}</ul>'


def _stat(label: str, value: str, unit: str = "") -> str:
    unit_markup = f'<span class="unit">{e(unit)}</span>' if unit else ""
    return (
        f'<div class="stat"><dt>{e(label)}</dt>'
        f'<dd><span class="figure">{e(value)}</span>{unit_markup}</dd></div>'
    )


def _stats(week: dict) -> str:
    parts = [
        _stat("Distance", f"{week['run_distance_km']:g}", "km"),
        _stat("Runs", str(week["run_count"])),
        _stat("Gym sessions", str(week["gym_count"])),
        _stat("Moving time", f"{week['total_time_min'] // 60}h {week['total_time_min'] % 60:02d}m"),
    ]
    if week.get("avg_pace"):
        parts.append(_stat("Average pace", week["avg_pace"], "/km"))
    if week.get("longest_run_km"):
        parts.append(_stat("Longest run", f"{week['longest_run_km']:g}", "km"))
    if week.get("run_elevation_m"):
        parts.append(_stat("Climbing", f"{week['run_elevation_m']:,}", "m"))
    parts.append(_stat("Days trained", f"{week['trained_days']}", "of 7"))
    if week.get("distance_change_pct") is not None:
        change = week["distance_change_pct"]
        parts.append(_stat("Versus your norm", f"{change:+d}", "%"))
    if week.get("acwr"):
        parts.append(_stat("Load ratio", f"{week['acwr']:.2f}"))
    return f'<dl class="stats">{"".join(parts)}</dl>'


def _trend(history: list[dict]) -> str:
    recent = history[-12:]
    if len(recent) < 2:
        return ""
    peak = max([w["run_distance_km"] for w in recent] + [1])
    bars = []
    for index, week in enumerate(recent):
        height = max(2, round(week["run_distance_km"] / peak * 100))
        current = " current" if index == len(recent) - 1 else ""
        bars.append(
            f'<div class="tbar{current}" style="--h:{height}%" '
            f'title="{e(week["label"])}: {week["run_distance_km"]:g} km"></div>'
        )
    return (
        '<section class="trend"><h2>Running distance, last twelve weeks</h2>'
        f'<div class="trendbars">{"".join(bars)}</div>'
        f'<p class="scale">{recent[0]["label"]} to {recent[-1]["label"]}'
        f' &middot; peak {peak:g} km</p></section>'
    )


def _archive(entries: list[dict]) -> str:
    if not entries:
        return ""
    blocks = []
    for entry in reversed(entries):
        week, review = entry["week"], entry["review"]
        blocks.append(
            f"<details><summary><span class=\"awhen\">{e(week['label'])}</span>"
            f"<span class=\"awhat\">{e(review.get('headline', ''))}</span>"
            f"<span class=\"akm\">{week['run_distance_km']:g} km</span></summary>"
            f'<div class="abody">{_exchange(review.get("exchange", []))}'
            f"{_tips(review.get('next_week', []))}</div></details>"
        )
    return f'<section class="archive"><h2>Earlier weeks</h2>{"".join(blocks)}</section>'


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="Weekly training review">
<meta name="color-scheme" content="light dark">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;700&family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap" rel="stylesheet">
<style>
:root {{
  --paper: #e7e9e3;
  --ink: #16211e;
  --muted: #5c6a64;
  --rule: #c9cfc7;
  --run: #2f6b58;
  --lift: #9d5a3c;
  --ash: #9ea8a2;
  --signal: #6f7d18;
  --sans: "Archivo", system-ui, -apple-system, "Segoe UI", sans-serif;
  --serif: "Newsreader", Georgia, "Times New Roman", serif;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --paper: #0f1a18;
    --ink: #e2e7e1;
    --muted: #93a099;
    --rule: #26332f;
    --run: #4e9e84;
    --lift: #c9805c;
    --ash: #566159;
    --signal: #cbd84a;
  }}
}}
* {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  margin: 0;
  padding: clamp(1.5rem, 5vw, 4rem) clamp(1.15rem, 5vw, 2rem) 5rem;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--sans);
  font-variant-numeric: tabular-nums;
  line-height: 1.5;
}}
main {{ max-width: 46rem; margin: 0 auto; }}
h1, h2 {{ font-weight: 700; letter-spacing: -0.015em; }}

.when {{ color: var(--muted); font-size: 0.875rem; margin: 0 0 1.75rem; }}

/* Hero: the shape of the week */
.week {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: clamp(4px, 1.4vw, 10px); }}
.day {{ display: flex; flex-direction: column; min-width: 0; }}
.track {{
  height: clamp(96px, 26vw, 168px);
  display: flex; align-items: flex-end;
  border-bottom: 2px solid var(--ink);
}}
.bar {{
  width: 100%; height: var(--h);
  animation: grow .6s cubic-bezier(.2,.8,.3,1) both;
  animation-delay: calc(var(--i) * 55ms);
}}
.bar.run {{ background: var(--run); }}
.bar.lift {{ background: var(--lift); }}
.bar.ash {{ background: var(--ash); }}
.bar.rest {{ background: var(--rule); }}
@keyframes grow {{ from {{ height: 0; }} to {{ height: var(--h); }} }}
@media (prefers-reduced-motion: reduce) {{ .bar {{ animation: none; }} }}
.dayname {{ font-size: 0.75rem; color: var(--muted); padding-top: .4rem; }}
.dayval {{ font-size: 0.75rem; font-weight: 500; }}

.key {{ display: flex; gap: 1.25rem; margin: 1.1rem 0 0; padding: 0; list-style: none;
  font-size: 0.8125rem; color: var(--muted); }}
.key span {{ display: inline-block; width: .6rem; height: .6rem; margin-right: .4rem; }}
.key .k-run {{ background: var(--run); }}
.key .k-lift {{ background: var(--lift); }}
.key .k-rest {{ background: var(--rule); }}

h1 {{ font-size: clamp(1.6rem, 5.5vw, 2.4rem); line-height: 1.12; margin: 2rem 0 0; }}

/* The argument. Each coach keeps one colour throughout the page. */
.exchange {{ margin: 1.5rem 0 2.5rem; max-width: 36em; }}
.turn {{ padding: 0 0 0 1.1rem; border-left: 3px solid; margin-bottom: 1.5rem; }}
.turn.snark {{ border-color: var(--lift); }}
.turn.kind {{ border-color: var(--run); }}
.who {{ font-size: 0.8125rem; font-weight: 700; margin: 0 0 .35rem; }}
.turn.snark .who {{ color: var(--lift); }}
.turn.kind .who {{ color: var(--run); }}
.said {{
  font-family: var(--serif); font-size: 1.125rem; line-height: 1.6; margin: 0;
}}

.tips {{ list-style: none; padding: 0; margin: 0; max-width: 36em; }}
.tip {{ padding: .55rem 0 .55rem 1.1rem; border-left: 3px solid; margin-bottom: .5rem; }}
.tip.snark {{ border-color: var(--lift); }}
.tip.kind {{ border-color: var(--run); }}
.from {{ display: block; font-size: 0.75rem; font-weight: 700; }}
.tip.snark .from {{ color: var(--lift); }}
.tip.kind .from {{ color: var(--run); }}
.advice {{ display: block; }}

h2 {{ font-size: 0.9375rem; margin: 2.5rem 0 .85rem;
  padding-bottom: .4rem; border-bottom: 1px solid var(--rule); }}

.marks {{ list-style: none; padding: 0; margin: 0; max-width: 36em; }}
.marks li {{ padding: .45rem 0 .45rem 1.4rem; position: relative; }}
.marks li::before {{ position: absolute; left: 0; top: .45rem; font-weight: 700; }}
.marks li.good::before {{ content: "\\2713"; color: var(--run); }}
.marks li.watch::before {{ content: "\\2022"; color: var(--lift); }}
.marks li.next::before {{ content: "\\2192"; color: var(--muted); }}

.stats {{ display: grid; gap: 1px 1px; margin: 0;
  grid-template-columns: repeat(auto-fit, minmax(7.5rem, 1fr));
  background: var(--rule); border: 1px solid var(--rule); }}
.stat {{ background: var(--paper); padding: .8rem .9rem; }}
.stat dt {{ font-size: 0.75rem; color: var(--muted); }}
.stat dd {{ margin: .15rem 0 0; }}
.figure {{ font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; }}
.unit {{ font-size: 0.8125rem; color: var(--muted); margin-left: .2rem; }}

.trendbars {{ display: flex; align-items: flex-end; gap: 3px;
  height: 72px; border-bottom: 1px solid var(--rule); }}
.tbar {{ flex: 1; height: var(--h); background: var(--rule); }}
.tbar.current {{ background: var(--run); }}
.scale {{ font-size: 0.75rem; color: var(--muted); margin: .5rem 0 0; }}

details {{ border-bottom: 1px solid var(--rule); }}
summary {{ cursor: pointer; padding: .7rem 0; display: flex; gap: .85rem;
  align-items: baseline; font-size: 0.9375rem; }}
summary::-webkit-details-marker {{ display: none; }}
.awhen {{ color: var(--muted); font-size: 0.8125rem; min-width: 6.5rem; }}
.awhat {{ flex: 1; }}
.akm {{ font-weight: 700; }}
.abody {{ padding: 0 0 1rem; max-width: 34em; }}
.abody p {{ font-family: var(--serif); margin: 0 0 .75rem; }}

footer {{ margin-top: 3.5rem; padding-top: 1rem; border-top: 1px solid var(--rule);
  font-size: 0.75rem; color: var(--muted); }}
a {{ color: inherit; }}
:focus-visible {{ outline: 2px solid var(--signal); outline-offset: 3px; }}
</style>
</head>
<body>
<main>
  <p class="when">Week of {label}</p>
  <div class="week">{bars}</div>
  <ul class="key">
    <li><span class="k-run"></span>Run</li>
    <li><span class="k-lift"></span>Gym</li>
    <li><span class="k-rest"></span>Rest</li>
  </ul>

  <h1>{headline}</h1>

  {exchange}

  {went_well_block}
  {watch_block}

  <h2>What they want from you this week</h2>
  {next_block}

  <h2>The numbers</h2>
  {stats}

  {trend}
  {archive}

  <footer>
    Built from your Strava activities on {generated}, by {engine}.<br>
    The commentary comes from an app that simulates two coaches arguing about
    one athlete's training. The numbers are real; the coaches are not.
  </footer>
</main>
</body>
</html>
"""


def render(history: list[dict], reviews: dict, config: dict, out_path: Path) -> None:
    week = history[-1]
    review = reviews[week["week_id"]]

    went_well = _list(review.get("went_well", []), "good")
    watch = _list(review.get("watch_out", []), "watch")

    archive_entries = [
        {"week": w, "review": reviews[w["week_id"]]}
        for w in history[:-1]
        if w["week_id"] in reviews
    ]

    tz = ZoneInfo(config.get("timezone", "Africa/Johannesburg"))
    now = datetime.now(tz)
    engine = review.get("generated_by", "unknown")
    engine = "a rules-based fallback" if engine == "fallback" else engine

    page = TEMPLATE.format(
        title=f"Training week {week['label']}",
        label=e(week["label"]),
        bars=_bars(week["days"]),
        headline=e(review.get("headline", "Your week")),
        exchange=_exchange(review.get("exchange", [])),
        went_well_block=(f"<h2>What went well</h2>{went_well}" if went_well else ""),
        watch_block=(f"<h2>Worth watching</h2>{watch}" if watch else ""),
        next_block=_tips(review.get("next_week", [])),
        stats=_stats(week),
        trend=_trend(history),
        archive=_archive(archive_entries),
        generated=f"{now.day} {now.strftime('%B %Y at %H:%M')}",
        engine=e(engine),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    (out_path.parent / ".nojekyll").touch()
    print(f"Wrote {out_path} ({len(page):,} bytes)")


def save_history(history: list[dict], reviews: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"weeks": history, "reviews": reviews}, indent=2),
        encoding="utf-8",
    )


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"weeks": [], "reviews": {}}
    return json.loads(path.read_text(encoding="utf-8"))
