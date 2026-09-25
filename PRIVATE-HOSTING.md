# Private hosting

The default setup publishes to GitHub Pages, which on a free plan means a public
repo and a publicly readable report. This is the alternative: the repo stays
private, the page lives on Cloudflare Pages, and Cloudflare Access puts a login
wall in front of it so only you can open it.

Both are free. This one is more private and costs one extra platform.

## Why not just pay GitHub?

A common assumption, and it doesn't work. GitHub Pro lets you *publish from* a
private repository, but the published site is still open to anyone with the URL —
only the source is hidden. Genuinely private Pages needs GitHub Enterprise Cloud,
which is not a sensible purchase for a running log.

Cloudflare Access is free for up to 50 users, which for one athlete is generous.

## What changes

```
GitHub repo (private)
  Actions runs the job  ->  builds docs/index.html
                        ->  wrangler pages deploy  ->  Cloudflare Pages
                        ->  commits data/history.json back to the repo
Cloudflare Access  ->  login wall in front of the page
```

`data/history.json` still gets committed, because the job needs its own history
between runs. It is now inside a private repo. The rendered page is no longer
committed at all.

## Setup

### 1. Make the repo private

If it's already public, Settings → General → Danger Zone → Change visibility. The
free plan gives unlimited private repos and 2,000 Action minutes a month; this
job uses about four.

### 2. Create the Pages project

```bash
npm install -g wrangler
wrangler login
python scripts/run_weekly.py --demo          # gives you a docs/ to upload
wrangler pages project create strava-report --production-branch=main
wrangler pages deploy docs --project-name=strava-report
```

That prints your URL, something like `strava-report.pages.dev`. It is public at
this point. Step 4 fixes that.

### 3. Let the Action deploy

Create an API token at **dash.cloudflare.com → My Profile → API Tokens → Create
Token**, using the "Edit Cloudflare Workers" template, or a custom token with
**Account → Cloudflare Pages → Edit**.

Add two repository secrets:

| Secret | Where to find it |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | The token you just made |
| `CLOUDFLARE_ACCOUNT_ID` | Right-hand sidebar of the Cloudflare dashboard |

If you named the project something other than `strava-report`, add a repository
**variable** `CF_PAGES_PROJECT` with your name.

Then delete `.github/workflows/weekly-report.yml` so the GitHub Pages version
doesn't run alongside this one. Keep `weekly-report-cloudflare.yml`.

### 4. Put the wall up

In the Cloudflare dashboard: **Zero Trust → Access → Applications → Add an
application → Self-hosted**.

- Application domain: your `strava-report.pages.dev`
- Add a policy: Action **Allow**, rule **Emails**, value: your email address
- Under login methods, **One-time PIN** is enough — no identity provider needed

Session duration is worth setting to something long, a month or so, unless you
enjoy typing codes.

Test it in a private browser window. If it loads without asking who you are, the
policy isn't attached to the right hostname.

### 5. Run it

Actions → Weekly training report (private) → Run workflow.

## What you get

Opening the page emails you a six-digit code the first time, then remembers you
for as long as the session lasts. Nobody else can read it. `config.json` and
`history.json` are inside a private repo.

## What it costs

Nothing. Cloudflare Pages free tier covers 500 builds a month and unlimited
requests; you use four builds. Access is free to 50 users. GitHub private repos
and their Action minutes are free at this scale.

## Trade-offs

You now depend on Cloudflare as well as GitHub, and there's a login step between
you and your own training data. If the page is something you want to glance at
from a phone on a Monday morning, that friction is real — a long session duration
mostly removes it.

If you'd rather go back, restore `weekly-report.yml`, make the repo public and
re-enable GitHub Pages. Nothing in `scripts/` changes either way; only the
delivery step differs.
