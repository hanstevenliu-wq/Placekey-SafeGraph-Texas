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
python send_report.py
```

Output:

- `geocoded_results.csv` — cumulative results (append-only; new rows added each day)
- `output/progress.json` — run summary
- `output/key_status.json` — per-key quota status
- GitHub Issue comment — daily progress and exhausted keys

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

## Cursor automation

1. Push this repo to GitHub.
2. Create a Cursor Cloud Environment pointing at the repo.
3. Add the four Placekey secrets.
4. Schedule a daily automation:

```bash
python geocode.py && python send_report.py
```

5. Snapshot the environment after the first run so results persist.

## Notes

- Do not commit `geocoded_results.csv` (gitignored; persists in Cursor snapshot).
- Re-running skips POIs already in the output CSV.
