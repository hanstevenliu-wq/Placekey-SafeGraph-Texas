"""
Post a daily geocoding progress report as a comment on a GitHub tracking issue.

Creates the issue on first run, then comments each day with progress and
exhausted Placekey API keys.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_CSV = ROOT / "geocoded_results.csv"
INPUT_CSV = ROOT / "texas.csv"
PROGRESS_JSON = OUTPUT_DIR / "progress.json"
KEY_STATUS_JSON = OUTPUT_DIR / "key_status.json"
REPORT_ISSUE_JSON = OUTPUT_DIR / "report_issue.json"

ISSUE_TITLE = "SafeGraph Texas Geocoding — Daily Progress"
DEFAULT_REPO = "hanstevenliu-wq/Placekey-SafeGraph-Texas"


def github_token() -> str:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "CURSOR_GITHUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def github_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "placekey-safegraph-texas",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def count_success_today() -> tuple[int, int]:
    if not OUTPUT_CSV.exists():
        return 0, 0
    df = pd.read_csv(OUTPUT_CSV, dtype=str)
    if df.empty or "geocoded_at" not in df.columns:
        return 0, 0

    today = pd.Timestamp.utcnow().date()
    df["geocoded_at"] = pd.to_datetime(df["geocoded_at"], utc=True, errors="coerce")
    today_df = df[df["geocoded_at"].dt.date == today]
    success = today_df["placekey"].notna() & (today_df["placekey"] != "")
    return int(len(today_df)), int(success.sum())


def build_report_body(progress: dict, key_status: dict) -> str:
    total = progress.get("total_rows", 0)
    completed = progress.get("completed_rows", 0)
    remaining = progress.get("remaining_rows", max(total - completed, 0))
    processed_today = progress.get("processed_this_run", 0)
    today_rows, today_success = count_success_today()
    run_time = progress.get("last_run_utc", "unknown")

    lines = [
        f"## Daily Progress Report — {run_time}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Processed this run | {processed_today:,} |",
        f"| Rows geocoded today (UTC) | {today_rows:,} |",
        f"| Successful today | {today_success:,} |",
        f"| Cumulative completed | {completed:,} |",
        f"| Remaining | {remaining:,} |",
        f"| Total POIs | {total:,} |",
        "",
        "### API key status",
        "",
    ]

    if not key_status:
        lines.append("_No key status recorded for this run._")
    else:
        lines.append("| Key | Status | Queries this run |")
        lines.append("| --- | --- | --- |")
        for label, info in key_status.items():
            status = info.get("status", "unknown")
            queries = info.get("queries_this_run", 0)
            lines.append(f"| {label} | {status} | {queries:,} |")

    exhausted = {
        label: info
        for label, info in key_status.items()
        if info.get("status") == "exhausted"
    }
    lines.extend(["", "### Expired / exhausted API keys", ""])
    if not exhausted:
        lines.append("_None — all keys still have quota or were not used._")
    else:
        for label, info in exhausted.items():
            msg = info.get("last_429_message", "quota exhausted (HTTP 429)")
            at = info.get("exhausted_at_utc", "unknown")
            lines.append(f"- **{label}** (exhausted at {at}): `{msg}`")

    if remaining == 0 and total > 0:
        lines.extend(["", "**Geocoding complete.** All POIs in `texas.csv` have been processed."])

    return "\n".join(lines)


def ensure_issue(token: str, repo: str) -> int:
    if REPORT_ISSUE_JSON.exists():
        data = json.loads(REPORT_ISSUE_JSON.read_text())
        if "issue_number" in data:
            return int(data["issue_number"])

    url = f"https://api.github.com/repos/{repo}/issues"
    body = (
        "Tracking issue for daily SafeGraph Texas Placekey geocoding automation.\n\n"
        "Each daily run posts a progress comment here, including exhausted API keys."
    )
    issue = github_request("POST", url, token, {"title": ISSUE_TITLE, "body": body})
    issue_number = int(issue["number"])
    REPORT_ISSUE_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_ISSUE_JSON.write_text(
        json.dumps(
            {
                "issue_number": issue_number,
                "issue_url": issue.get("html_url"),
                "repo": repo,
            },
            indent=2,
        )
    )
    print(f"Created tracking issue #{issue_number}: {issue.get('html_url')}")
    return issue_number


def post_comment(token: str, repo: str, issue_number: int, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    comment = github_request("POST", url, token, {"body": body})
    print(f"Posted comment: {comment.get('html_url')}")


def main() -> None:
    token = github_token()
    if not token:
        print("Set GITHUB_TOKEN (or GH_TOKEN / CURSOR_GITHUB_TOKEN) for issue reporting.", file=sys.stderr)
        sys.exit(1)

    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO
    progress = load_json(PROGRESS_JSON)
    key_status = load_json(KEY_STATUS_JSON)

    if not progress:
        total_rows = len(pd.read_csv(INPUT_CSV, dtype=str)) if INPUT_CSV.exists() else 0
        completed_rows = len(pd.read_csv(OUTPUT_CSV, dtype=str)) if OUTPUT_CSV.exists() else 0
        progress = {
            "total_rows": total_rows,
            "completed_rows": completed_rows,
            "remaining_rows": max(total_rows - completed_rows, 0),
            "processed_this_run": 0,
            "last_run_utc": pd.Timestamp.utcnow().isoformat(),
        }

    body = build_report_body(progress, key_status)

    try:
        issue_number = ensure_issue(token, repo)
        post_comment(token, repo, issue_number, body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"GitHub API error ({exc.code}): {detail}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
