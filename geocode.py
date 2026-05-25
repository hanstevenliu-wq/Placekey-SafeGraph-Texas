"""
Geocode SafeGraph Texas POIs with the Placekey API using multiple API keys.

Processes up to 40,000 rows per run (4 keys × 10,000 each), skips rows already
in geocoded_results.csv, and appends new results each day.

Set Placekey secrets in the environment (Cursor automation):
  placekey_utsa, placekey_icloud, placekey_gmail, placekey_brown
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
INPUT_CSV = ROOT / "texas.csv"
OUTPUT_DIR = ROOT / "output"
OUTPUT_CSV = ROOT / "geocoded_results.csv"
PROGRESS_JSON = OUTPUT_DIR / "progress.json"
KEY_STATUS_JSON = OUTPUT_DIR / "key_status.json"

API_URL = "https://api.placekey.io/v1/placekeys"
BATCH_SIZE = 100
QUERIES_PER_KEY = 10_000
SAVE_EVERY_N_BATCHES = 5

API_KEY_SPECS: list[tuple[str, tuple[str, ...]]] = [
    ("utsa", ("PLACEKEY_UTSA", "placekey_utsa")),
    ("icloud", ("PLACEKEY_ICLOUD", "placekey_icloud")),
    ("gmail", ("PLACEKEY_GMAIL", "placekey_gmail")),
    ("brown", ("PLACEKEY_BROWN", "placekey_brown")),
]

OUTPUT_COLUMNS = [
    "safegraph_place_id",
    "location_name",
    "street_address",
    "city",
    "state",
    "zip_code",
    "placekey",
    "latitude",
    "longitude",
    "confidence_score",
    "location_type",
    "error",
    "api_key_used",
    "geocoded_at",
]


def env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def load_api_keys() -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for label, env_names in API_KEY_SPECS:
        value = env_value(*env_names)
        if value:
            keys.append((label, value))
    return keys


def load_addresses() -> pd.DataFrame:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_CSV}")
    return pd.read_csv(INPUT_CSV, dtype=str)


def load_completed_ids() -> set[str]:
    if not OUTPUT_CSV.exists():
        return set()
    done = pd.read_csv(OUTPUT_CSV, usecols=["safegraph_place_id", "placekey"], dtype=str)
    success = done["placekey"].notna() & (done["placekey"] != "")
    return set(done.loc[success, "safegraph_place_id"].dropna())


def build_query(row: pd.Series) -> dict:
    return {
        "query_id": str(row["safegraph_place_id"]).strip(),
        "location_name": str(row.get("location_name", "") or "").strip(),
        "street_address": str(row.get("street_address", "") or "").strip(),
        "city": str(row.get("city", "") or "").strip(),
        "region": str(row.get("state", "") or "").strip(),
        "postal_code": str(row.get("zip_code", "") or "").strip(),
        "iso_country_code": "US",
    }


def call_placekey_batch(
    session: requests.Session,
    api_key: str,
    queries: list[dict],
) -> tuple[int, list[dict] | None, str]:
    payload = {
        "queries": queries,
        "options": {"fields": ["geocode", "confidence_score"]},
    }
    response = session.post(
        API_URL,
        headers={"apikey": api_key, "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=120,
    )

    if response.status_code == 429:
        detail = response.text[:500]
        try:
            detail = json.dumps(response.json())
        except Exception:
            pass
        return 429, None, detail

    if not response.ok:
        return response.status_code, None, response.text[:500]

    data = response.json()
    if not isinstance(data, list):
        return response.status_code, None, f"Unexpected API response: {data}"
    return 200, data, ""


def flatten_result(row: pd.Series, api_result: dict, key_label: str) -> dict:
    geocode = api_result.get("geocode") or {}
    location = geocode.get("location") or {}

    return {
        "safegraph_place_id": row.get("safegraph_place_id"),
        "location_name": row.get("location_name"),
        "street_address": row.get("street_address"),
        "city": row.get("city"),
        "state": row.get("state"),
        "zip_code": row.get("zip_code"),
        "placekey": api_result.get("placekey"),
        "latitude": location.get("lat"),
        "longitude": location.get("lng"),
        "confidence_score": api_result.get("confidence_score"),
        "location_type": geocode.get("location_type"),
        "error": api_result.get("error"),
        "api_key_used": key_label,
        "geocoded_at": pd.Timestamp.utcnow().isoformat(),
    }


def append_results(rows: list[dict]) -> None:
    if not rows:
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    write_header = not OUTPUT_CSV.exists()
    new_df.to_csv(OUTPUT_CSV, mode="a", index=False, header=write_header)


def save_progress(
    *,
    total_rows: int,
    completed_rows: int,
    processed_this_run: int,
    key_status: dict,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    progress = {
        "total_rows": total_rows,
        "completed_rows": completed_rows,
        "remaining_rows": max(total_rows - completed_rows, 0),
        "processed_this_run": processed_this_run,
        "daily_quota": QUERIES_PER_KEY * len(API_KEY_SPECS),
        "output_file": str(OUTPUT_CSV),
        "last_run_utc": pd.Timestamp.utcnow().isoformat(),
    }
    PROGRESS_JSON.write_text(json.dumps(progress, indent=2))
    KEY_STATUS_JSON.write_text(json.dumps(key_status, indent=2))
    print(json.dumps(progress, indent=2))


def main() -> None:
    api_keys = load_api_keys()
    if not api_keys:
        print(
            "Set at least one Placekey secret: placekey_utsa, placekey_icloud, "
            "placekey_gmail, placekey_brown",
            file=sys.stderr,
        )
        sys.exit(1)

    sleep_seconds = float(os.environ.get("REQUEST_SLEEP_SECONDS", "0.2"))
    run_limit = os.environ.get("DAILY_LIMIT", "").strip()
    max_total = int(run_limit) if run_limit else QUERIES_PER_KEY * len(api_keys)

    addresses = load_addresses()
    completed_ids = load_completed_ids()
    pending = addresses[~addresses["safegraph_place_id"].isin(completed_ids)].copy()

    if pending.empty:
        print(f"All {len(addresses):,} POIs are already geocoded.")
        save_progress(
            total_rows=len(addresses),
            completed_rows=len(completed_ids),
            processed_this_run=0,
            key_status={label: {"status": "skipped", "queries_this_run": 0} for label, _ in api_keys},
        )
        return

    print(
        f"Pending: {len(pending):,} | Max this run: {max_total:,} | "
        f"Already done: {len(completed_ids):,} | Total: {len(addresses):,}"
    )

    session = requests.Session()
    results_buffer: list[dict] = []
    processed_this_run = 0
    pending_index = 0
    key_status: dict[str, dict] = {}

    for key_label, api_key in api_keys:
        if processed_this_run >= max_total or pending_index >= len(pending):
            key_status[key_label] = {"status": "skipped", "queries_this_run": 0}
            continue

        remaining_run = max_total - processed_this_run
        key_quota = min(QUERIES_PER_KEY, remaining_run, len(pending) - pending_index)
        key_processed = 0
        batches_since_save = 0
        status = "available"

        print(f"[{key_label}] Starting (quota: {key_quota:,})")

        while key_processed < key_quota and pending_index < len(pending):
            chunk_size = min(BATCH_SIZE, key_quota - key_processed, len(pending) - pending_index)
            chunk = pending.iloc[pending_index : pending_index + chunk_size]
            queries = [build_query(row) for _, row in chunk.iterrows()]

            status_code, api_results, detail = call_placekey_batch(session, api_key, queries)

            if status_code == 429:
                status = "exhausted"
                print(f"[{key_label}] Rate limit (429): {detail}")
                key_status[key_label] = {
                    "status": "exhausted",
                    "queries_this_run": key_processed,
                    "exhausted_at_utc": pd.Timestamp.utcnow().isoformat(),
                    "last_429_message": detail,
                }
                break

            if status_code == 401:
                status = "invalid_key"
                print(f"[{key_label}] Unauthorized (401), skipping key: {detail}")
                key_status[key_label] = {
                    "status": "invalid_key",
                    "queries_this_run": key_processed,
                    "invalid_at_utc": pd.Timestamp.utcnow().isoformat(),
                    "last_401_message": detail,
                }
                break

            if api_results is None:
                print(f"[{key_label}] API error {status_code}: {detail}", file=sys.stderr)
                for _, row in chunk.iterrows():
                    results_buffer.append(
                        flatten_result(row, {"error": f"http_{status_code}"}, key_label)
                    )
            else:
                by_id = {str(item.get("query_id")): item for item in api_results}
                for _, row in chunk.iterrows():
                    poi_id = str(row["safegraph_place_id"])
                    api_result = by_id.get(poi_id, {"error": "missing_api_result"})
                    results_buffer.append(flatten_result(row, api_result, key_label))

            pending_index += chunk_size
            key_processed += chunk_size
            processed_this_run += chunk_size
            batches_since_save += 1

            print(
                f"[{key_label}] Processed {key_processed:,}/{key_quota:,} "
                f"(run total: {processed_this_run:,})"
            )

            if batches_since_save >= SAVE_EVERY_N_BATCHES:
                append_results(results_buffer)
                results_buffer = []
                batches_since_save = 0

            time.sleep(sleep_seconds)

        if key_label not in key_status:
            key_status[key_label] = {
                "status": status,
                "queries_this_run": key_processed,
            }

    append_results(results_buffer)

    completed_rows = len(load_completed_ids())
    save_progress(
        total_rows=len(addresses),
        completed_rows=completed_rows,
        processed_this_run=processed_this_run,
        key_status=key_status,
    )
    remaining = len(addresses) - completed_rows
    print(f"Done for today. Remaining: {remaining:,}")


if __name__ == "__main__":
    main()
