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

Run once per day:

```bash
python geocode.py && python send_report.py
```

- `geocode.py` — geocodes up to 40,000 pending POIs (4 keys × 10k), appends to `geocoded_results.csv`
- `send_report.py` — posts progress comment on the GitHub tracking issue

After the first successful run, **snapshot the environment** so `geocoded_results.csv` and `output/` persist.

### Optional env vars

| Variable | Default | Description |
| --- | --- | --- |
| `DAILY_LIMIT` | `40000` | Max rows per run (override for testing) |
| `REQUEST_SLEEP_SECONDS` | `0.2` | Pause between API batches |
| `GITHUB_REPO` | `hanstevenliu-wq/Placekey-SafeGraph-Texas` | Repo for issue comments |
