# Weekly training review

Every Monday at 06:00 SAST, a GitHub Action pulls your Strava activities for the
week that just finished, works out what actually happened, asks a language model
to write you a short coaching note, and publishes it to a GitHub Pages site.

No server, no database, no cost.

```
GitHub Actions (cron, Monday 04:00 UTC)
  -> refresh Strava token -> fetch 12 weeks of activities
  -> compute metrics (analyze.py)
  -> write the review (coach.py, Gemini or Groq free tier)
  -> render docs/index.html + commit data/history.json
  -> GitHub Pages serves the page
```

## See it before you build it

```bash
pip install -r requirements.txt
python scripts/run_weekly.py --demo
open docs/index.html
```

That uses generated sample data and needs no credentials. Delete
`data/history.json` afterwards so your first real run starts clean.

## Setup

### 1. Strava app

Go to <https://www.strava.com/settings/api> and create an app. Set
**Authorization Callback Domain** to exactly `localhost`. Note the Client ID and
Client Secret.

### 2. Refresh token

```bash
python scripts/get_refresh_token.py
```

This opens Strava, catches the redirect, and prints your refresh token. Tick the
box for private activities or they will be skipped.

Access tokens expire every 6 hours, which is why we store the *refresh* token and
mint a fresh access token on each run.

The token is read-only. This app never writes anything back to Strava, so it
doesn't request the `activity:write` scope. If a token ever leaks, the worst
anyone gets is a look at your activities.

### 3. Free LLM key

Either one:

- **Gemini** — <https://aistudio.google.com/apikey>. Free tier is generous; one
  call a week is nothing. Default model is `gemini-flash-latest`, an alias that
  tracks Google's current Flash model, so it survives version churn.
- **Groq** — <https://console.groq.com/keys>. Set the `LLM_PROVIDER` repository
  variable to `groq`.

### 4. Repository secrets

Settings → Secrets and variables → Actions → **Secrets**:

| Secret | Required | What it is |
| --- | --- | --- |
| `STRAVA_CLIENT_ID` | yes | From your Strava app |
| `STRAVA_CLIENT_SECRET` | yes | From your Strava app |
| `STRAVA_REFRESH_TOKEN` | yes | From step 2 |
| `GEMINI_API_KEY` | one of | Gemini key |
| `GROQ_API_KEY` | one of | Groq key |
| `GH_PAT` | optional | See "token rotation" below |

Under **Variables**, optionally set `LLM_PROVIDER` (`gemini` or `groq`) and
`LLM_MODEL` to pin a specific model.

### 5. Turn on Pages

Settings → Pages → Source: **Deploy from a branch** → Branch `main`, folder
`/docs`. Your page lands at `https://<you>.github.io/<repo>/`.

### 6. Tune config.json

```json
{
  "timezone": "Africa/Johannesburg",
  "max_heart_rate": 190,
  "easy_hr_ceiling": 0.78,
  "goals": {
    "weekly_distance_km": 40,
    "gym_sessions_per_week": 2,
    "focus": "Build a consistent base while keeping two strength sessions a week",
    "target_event": null
  }
}
```

`max_heart_rate` drives the easy-versus-hard split, so a rough estimate is worse
than a real number. If you have never tested it, `220 - age` is a starting point
but often wrong by 10+ bpm. `focus` and `target_event` are fed straight to the
coach, so putting "Soweto Marathon in November" there changes what it tells you.

### 7. Run it

Actions → Weekly training report → **Run workflow**. Don't wait a week to find
out it's broken.

## What it measures

**Running** — distance, moving time, average pace, longest run, elevation, and an
easy/hard split based on average heart rate against your max.

**Gym** — session count and time. Strava's `WeightTraining`, `Workout`,
`Crossfit`, `HighIntensityIntervalTraining`, `Yoga` and `Pilates` all count.

**Both** — days trained out of seven, longest rest gap, and a training load per
session. Load uses Strava's Relative Effort when it's there, otherwise duration
scaled by heart-rate intensity.

**Trend** — this week's load divided by the average of the previous four weeks
(the acute-to-chronic ratio). Above roughly 1.5 tends to mean you ramped hard;
the coach is told to raise it.

These feed a short list of flags — `load_spike`, `mileage_jump`,
`too_much_intensity`, `gym_skipped`, `load_drop`, `no_training` — which the model
sees alongside the raw numbers. All the arithmetic happens in `analyze.py`, so the
model is only writing prose about facts, not inventing them.

## The two coaches

The review is written as an argument between two of them.

**Coach Dunkley** has seen thirty years of athletes and has never been impressed.
He finds the least flattering number in your week and builds his whole assessment
around it.

**Coach Amari** works at the same club, reads what Dunkley just wrote, and is
quietly furious about it. She answers him directly, then names the thing he
ignored.

They each end with one piece of advice for the coming week, so the page gives you
two, in their own voices. Who opens alternates every week, and both of them see
last Monday's exchange, so the argument carries forward instead of resetting.

That last part is what separates this from a stats page. By week three they are
referring back to things they said, and to whether you did any of it.

### How it's kept honest

Only the opinions come from the model. The headline, what went well and what's
worth watching are all computed in `coach.py` from the flags in `analyze.py`, so
the coaches are arguing about facts they cannot bend. Each one gets three or four
sentences and a single tip; nothing else.

Dunkley's prompt carries explicit limits: the contempt is aimed at the training
and never at you as a person, nothing about your body or your worth, and he never
implies you're wasting your time or pushes volume in a way you'd be unwise to act
on. Both coaches are told that a quiet week is not a failure and that the useful
response to one is helping you restart.

Rename them in `config.json` under `coaches`. If the bit stops landing, the
fallback exchange in `coach.py` shows the shape a plainer review would take.

## Token rotation

Strava sometimes issues a new refresh token during a refresh. If that happens and
the old one is still sitting in your secrets, the job dies the following week.

`strava_client.py` handles it: if you add a `GH_PAT` secret (a fine-grained
personal access token scoped to this repo with **Secrets: read and write**), it
writes the new token back automatically. Without it, the run logs a loud warning
with the new value so you can paste it in yourself.

## A note on privacy

GitHub Pages on a **private** repo needs a paid plan, and even then the published
site stays public — only the source is hidden. Genuinely private Pages requires
GitHub Enterprise Cloud. So on a free plan the repo must be public, which means
your page and `data/history.json` are public too.

What's actually in there: weekly aggregates, session names, distances, paces,
average heart rates, and the coaches' notes. No GPS traces, no addresses, no
start-point coordinates — the code never requests or stores them. Mild exposure,
but it's your call.

**If you'd rather it were private**, see `PRIVATE-HOSTING.md`. It keeps the repo
private and serves the page from Cloudflare Pages behind a login wall that only
lets your email address through. Also free, and the workflow for it is already in
`.github/workflows/weekly-report-cloudflare.yml`.

## Cost

Public repo: Actions minutes are unlimited. Private repo on the free plan: 2,000
minutes a month, and this job uses about one. Gemini and Groq free tiers both
cover one weekly call with enormous room to spare.

## Troubleshooting

**"Strava rejected the refresh token"** — it was revoked, or your client ID and
secret belong to a different app. Re-run `get_refresh_token.py`.

**The page says "a rules-based fallback" wrote it** — the LLM call failed and the
fallback in `coach.py` kicked in so the page still rendered. Check the Action log
for the actual error; usually a missing key or a model name that has been retired.

**Runs are missing** — you probably didn't grant `activity:read_all`, so private
activities are invisible. Re-run the token script and tick the box.

**Gym sessions aren't counting** — check what `sport_type` Strava is recording and
add it to `GYM_TYPES` in `analyze.py`.

**Empty week** — that's handled. The coach is told explicitly that a quiet week
isn't a failure and to help you restart rather than make you feel behind.

## Layout

```
.github/workflows/weekly-report.yml   the cron job (GitHub Pages)
.github/workflows/weekly-report-cloudflare.yml
                                      the cron job (private Cloudflare option)
PRIVATE-HOSTING.md                    how to run it behind a login wall
config.json                           your goals and max HR
scripts/get_refresh_token.py          one-time, run locally
scripts/strava_client.py              auth + fetch
scripts/analyze.py                    all the arithmetic
scripts/coach.py                      prompt, LLM call, fallback
scripts/render.py                     HTML generation
scripts/run_weekly.py                 entry point
data/history.json                     rolling record, committed each week
docs/index.html                       the published page
```
