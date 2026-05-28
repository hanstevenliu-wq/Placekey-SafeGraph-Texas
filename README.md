# SafeGraph Texas Placekey Geocoding

Geocode SafeGraph Texas POIs from `texas.csv` using the Placekey API. Processes up to **40,000 addresses per day** across four API keys and posts a daily progress report as a GitHub Issue comment.

## Data

Input: `texas.csv` (~58,073 POIs)

| Column | Description |
| --- | --- |
| `safegraph_place_id` | Unique POI ID |
| `location_name` | Business name |
| `street_address` | Street address |
| `city` | City |
| `state` | State |
| `zip_code` | ZIP code |

At 40,000/day, the file completes in about **2 days**.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set API keys (at least one required; all four for full daily quota):

```bash
export placekey_utsa="..."
export placekey_icloud="..."
export placekey_gmail="..."
export placekey_brown="..."
```

## Run daily geocoding

```bash
python geocode.py
python publish_release.py
python send_report.py
```

Output:

- `geocoded_results.csv` — cumulative results (append-only; new rows added each day)
- [GitHub Release](https://github.com/hanstevenliu-wq/Placekey-SafeGraph-Texas/releases/tag/geocoded-results-latest) — downloadable copy of the cumulative CSV (`geocoded_results.csv`)
- `output/progress.json` — run summary
- `output/key_status.json` — per-key quota status
- GitHub Issue comment — daily progress and exhausted keys
- Microsoft Teams message — same summary when `TEAMS_WEBHOOK_URL` or `teams_webhook_url` is set

## Output columns

`safegraph_place_id`, `location_name`, `street_address`, `city`, `state`, `zip_code`, `placekey`, `latitude`, `longitude`, `confidence_score`, `location_type`, `error`, `api_key_used`, `geocoded_at`

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `placekey_utsa` / `PLACEKEY_UTSA` | — | First API key |
| `placekey_icloud` / `PLACEKEY_ICLOUD` | — | Second API key |
| `placekey_gmail` / `PLACEKEY_GMAIL` | — | Third API key |
| `placekey_brown` / `PLACEKEY_BROWN` | — | Fourth API key |
| `DAILY_LIMIT` | `40000` | Max rows per run |
| `REQUEST_SLEEP_SECONDS` | `0.2` | Pause between batches |
| `GITHUB_REPO` | `hanstevenliu-wq/Placekey-SafeGraph-Texas` | Target repo for reports |
| `TEAMS_WEBHOOK_URL` / `teams_webhook_url` | — | Microsoft Teams Incoming Webhook URL |
| `CURSOR_API_KEY` | — | Optional: update Cursor automation cron via API |
| `GIT_COMMIT_SCHEDULE` | `1` | Set `0` to skip git commit in `reschedule_automation.py` |

## Cursor automation

1. Push this repo to GitHub.
2. Create a Cursor Cloud Environment pointing at the repo.
3. Add the four Placekey secrets, `GITHUB_TOKEN` (issues write), and `teams_webhook_url` (Teams daily report) for daily reports.
4. Create a Cursor automation with a **webhook** trigger (recommended). Paste the prompt from [`.cursor/automation-prompt.md`](.cursor/automation-prompt.md) (or run `./daily_run.sh` as the one-line version).

5. Wire the webhook to GitHub Actions (see **Webhook setup** below).
6. Snapshot the environment after the first run so results persist.

`merge_pr.py` merges automation code changes into `main` automatically after each run. Optional: `CURSOR_API_KEY` if Cursor exposes an automation schedule API for your team.

## Webhook setup

Your Cursor automation already uses a **Webhook triggered** entry (copy icon next to the URL). Connect it to the repo scheduler like this:

### A. In Cursor (you’ve mostly done this)

1. Open **SafeGraph Texas Daily Geocoding** at [cursor.com/automations](https://cursor.com/automations).
2. Under **Triggers**, keep **Webhook triggered** (remove any separate **Scheduled** cron on this automation to avoid double runs).
3. Copy the full webhook URL (`https://api2.cursor.sh/aut...`).
4. Click **Generate auth header** and copy the full header line (e.g. `Authorization: Bearer …`).

### B. In GitHub

1. Repo **Settings → Secrets and variables → Actions → New repository secret**
2. Add:

| Secret | Value |
| --- | --- |
| `CURSOR_AUTOMATION_WEBHOOK_URL` | The webhook URL from Cursor |
| `CURSOR_AUTOMATION_WEBHOOK_AUTH` | The full auth header from **Generate auth header** (optional if Cursor does not require it) |

3. Confirm workflow [`.github/workflows/trigger-daily-geocode.yml`](.github/workflows/trigger-daily-geocode.yml) is on `main`. It runs on the cron in [`.cursor/automation.json`](.cursor/automation.json) (currently **07:00 UTC**, +1 hour after each geocoding run).

### C. Test

**Manual run in GitHub:** Actions → **Trigger daily geocoding** → **Run workflow**.

**Or from a terminal** (replace with your URL and header):

```bash
curl -fsS -X POST "$CURSOR_AUTOMATION_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "$CURSOR_AUTOMATION_WEBHOOK_AUTH" \
  -d '{"source":"manual-test"}'
```

A new run should appear under your automation’s run history in Cursor.

## Microsoft Teams daily report

After each run, `send_report.py` posts the same progress summary to a Teams channel when a webhook URL is configured.

### Create the webhook

1. In Teams, open the channel where you want reports.
2. Click **⋯** → **Connectors** (or **Workflows** → **Post to a channel when a webhook request is received** on newer tenants).
3. Add an **Incoming Webhook** connector, name it (e.g. “SafeGraph Geocoding”), and copy the webhook URL.

### Add the secret

In your Cursor Cloud Environment, add:

| Secret | Value |
| --- | --- |
| `teams_webhook_url` | The Incoming Webhook URL from Teams |

Supported env names: `TEAMS_WEBHOOK_URL`, `teams_webhook_url`, or `TEAMS_WEBHOOK`.

The Teams message includes processed/remaining counts, per-key quota status, alerts for exhausted or invalid keys, and links to the latest CSV and GitHub tracking issue.

## Notes

- Do not commit `geocoded_results.csv` (gitignored; persists in Cursor snapshot).
- Re-running skips POIs already in the output CSV.
