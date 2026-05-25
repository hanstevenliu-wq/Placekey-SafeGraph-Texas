# Placekey SafeGraph Texas geocoding automation

## Cursor Cloud specific instructions

This repo geocodes SafeGraph Texas POIs from `texas.csv` using the Placekey API with four API keys (40,000 lookups/day).

### Required secrets

| Secret | Purpose |
| --- | --- |
| `placekey_utsa` | Placekey API key (10k/day) |
| `placekey_icloud` | Placekey API key (10k/day) |
| `placekey_gmail` | Placekey API key (10k/day) |
| `placekey_brown` | Placekey API key (10k/day) |

GitHub token for daily issue reports comes from the Cursor environment (`GITHUB_TOKEN` / `CURSOR_GITHUB_TOKEN`).

### Data file

- **Input:** `./texas.csv` (~58,073 POIs, committed in repo)
- **Output:** `./geocoded_results.csv` (append-only, gitignored, persists via environment snapshot)

### Setup

```bash
pip install -r requirements.txt
```

### Daily automation

**Cursor automation prompt:** copy from [`.cursor/automation-prompt.md`](.cursor/automation-prompt.md) into your automation at [cursor.com/automations](https://cursor.com/automations) (automation id in `.cursor/automation.json`).

Run once per day (full pipeline):

```bash
./daily_run.sh
```

Or step by step:

```bash
python3 geocode.py && python3 send_report.py && python3 reschedule_automation.py && python3 merge_pr.py
```

- `geocode.py` — geocodes up to 40,000 pending POIs (4 keys × 10k), appends to `geocoded_results.csv`
- `send_report.py` — posts progress comment on the GitHub tracking issue
- `reschedule_automation.py` — advances the next run by **1 hour** (updates `.cursor/automation.json` and `.github/workflows/trigger-daily-geocode.yml`, then commits to `main`)
- `merge_pr.py` — opens and merges a PR for the current branch into `main` (falls back to `git merge` if the GitHub app token cannot create PRs)

After the first successful run, **snapshot the environment** so `geocoded_results.csv` and `output/` persist.

**Schedule:** Initial cron is `0 6 * * *` UTC (see `.cursor/automation.json`). Each run bumps the hour so Placekey rolling-24h quotas refresh before the next batch. Prefer a **webhook** Cursor automation plus the GitHub Actions workflow (set repo secret `CURSOR_AUTOMATION_WEBHOOK_URL`); disable the fixed Cursor cron trigger to avoid double runs.

### Optional env vars

| Variable | Default | Description |
| --- | --- | --- |
| `DAILY_LIMIT` | `40000` | Max rows per run (override for testing) |
| `REQUEST_SLEEP_SECONDS` | `0.2` | Pause between API batches |
| `GITHUB_REPO` | `hanstevenliu-wq/Placekey-SafeGraph-Texas` | Repo for issue comments |
