Run the daily SafeGraph Texas Placekey geocoding job.

## Steps

1. Install dependencies: `pip install -r requirements.txt`
2. Run the full pipeline: `./daily_run.sh`

   This runs, in order:
   - `python3 geocode.py` — geocode pending POIs (up to 40k/day across four keys)
   - `python3 publish_release.py` — upload `geocoded_results.csv` to GitHub Releases
   - `python3 send_report.py` — post daily progress to the GitHub tracking issue
   - `python3 reschedule_automation.py` — advance tomorrow's schedule by 1 hour (UTC) so Placekey rolling-24h quotas refresh
   - `python3 merge_pr.py` — create and merge any code changes into `main`

## Secrets and data

- Use the four Placekey secrets: `placekey_utsa`, `placekey_icloud`, `placekey_gmail`, `placekey_brown`
- Use `GITHUB_TOKEN` or `CURSOR_GITHUB_TOKEN` (or `gh auth token`) for `send_report.py` and `publish_release.py`
- Do **not** modify `texas.csv` or overwrite `geocoded_results.csv` — only append new rows with successful geocodes
- `geocoded_results.csv` persists via the Cursor environment snapshot (gitignored)

## After geocoding

- If `geocode.py` completes successfully, `daily_run.sh` always runs `send_report.py`
- When `geocoded_results.csv` has data rows, `publish_release.py` uploads it to GitHub Releases
- Report any errors clearly (invalid keys HTTP 401, exhausted keys HTTP 429, missing GitHub token)
- Commit and push schedule updates from `reschedule_automation.py` to `main`
- Merge feature-branch changes with `merge_pr.py` when applicable

## Schedule

- Next run time is in `.cursor/automation.json` (`cron`, UTC)
- GitHub Actions `.github/workflows/trigger-daily-geocode.yml` triggers the webhook on that schedule
- Prefer a **webhook** trigger in this automation; avoid a second fixed cron that would double-run
