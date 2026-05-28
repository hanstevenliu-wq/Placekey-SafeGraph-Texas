"""
Post a daily geocoding progress report as a comment on a GitHub tracking issue
and as a Microsoft Teams message (Incoming Webhook).

Creates the issue on first run, then comments each day with progress and
exhausted Placekey API keys. When TEAMS_WEBHOOK_URL (or teams_webhook_url) is
set, the same summary is posted to Teams after the GitHub comment.
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
RELEASE_JSON = OUTPUT_DIR / "release.json"

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


def teams_webhook_url() -> str:
    for key in ("TEAMS_WEBHOOK_URL", "teams_webhook_url", "TEAMS_WEBHOOK"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def collect_report_metrics(progress: dict, key_status: dict) -> dict:
    total = progress.get("total_rows", 0)
    completed = progress.get("completed_rows", 0)
    remaining = progress.get("remaining_rows", max(total - completed, 0))
    processed_today = progress.get("processed_this_run", 0)
    today_rows, today_success = count_success_today()
    run_time = progress.get("last_run_utc", "unknown")

    exhausted = {
        label: info
        for label, info in key_status.items()
        if info.get("status") == "exhausted"
    }
    invalid = {
        label: info
        for label, info in key_status.items()
        if info.get("status") == "invalid_key"
    }

    release_info = load_json(RELEASE_JSON)
    latest = release_info.get("latest") if release_info else None
    download_url = latest.get("download_url") if latest else None
    dated_url = release_info.get("dated", {}).get("download_url") if release_info else None

    return {
        "total": total,
        "completed": completed,
        "remaining": remaining,
        "processed_today": processed_today,
        "today_rows": today_rows,
        "today_success": today_success,
        "run_time": run_time,
        "exhausted": exhausted,
        "invalid": invalid,
        "download_url": download_url,
        "dated_url": dated_url,
        "complete": remaining == 0 and total > 0,
    }


def build_report_body(progress: dict, key_status: dict) -> str:
    metrics = collect_report_metrics(progress, key_status)
    run_time = metrics["run_time"]

    lines = [
        f"## Daily Progress Report — {run_time}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Processed this run | {metrics['processed_today']:,} |",
        f"| Rows geocoded today (UTC) | {metrics['today_rows']:,} |",
        f"| Successful today | {metrics['today_success']:,} |",
        f"| Cumulative completed | {metrics['completed']:,} |",
        f"| Remaining | {metrics['remaining']:,} |",
        f"| Total POIs | {metrics['total']:,} |",
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

    lines.extend(["", "### Expired / exhausted API keys", ""])
    if not metrics["exhausted"]:
        lines.append("_None — all keys still have quota or were not used._")
    else:
        for label, info in metrics["exhausted"].items():
            msg = info.get("last_429_message", "quota exhausted (HTTP 429)")
            at = info.get("exhausted_at_utc", "unknown")
            lines.append(f"- **{label}** (exhausted at {at}): `{msg}`")

    if metrics["complete"]:
        lines.extend(["", "**Geocoding complete.** All POIs in `texas.csv` have been processed."])

    if metrics["download_url"]:
        lines.extend(
            [
                "",
                "### Download",
                "",
                f"- Latest CSV: [geocoded_results.csv]({metrics['download_url']})",
            ]
        )
        if metrics["dated_url"]:
            lines.append(f"- Today's snapshot: [geocoded_results.csv]({metrics['dated_url']})")

    return "\n".join(lines)


def build_teams_message(progress: dict, key_status: dict, issue_url: str | None = None) -> dict:
    metrics = collect_report_metrics(progress, key_status)
    theme_color = "107C10" if metrics["complete"] else "0078D4"
    if metrics["exhausted"] or metrics["invalid"]:
        theme_color = "D13438"

    facts = [
        {"name": "Processed this run", "value": f"{metrics['processed_today']:,}"},
        {"name": "Successful today (UTC)", "value": f"{metrics['today_success']:,}"},
        {"name": "Cumulative completed", "value": f"{metrics['completed']:,}"},
        {"name": "Remaining", "value": f"{metrics['remaining']:,}"},
        {"name": "Total POIs", "value": f"{metrics['total']:,}"},
    ]

    key_lines: list[str] = []
    if key_status:
        for label, info in key_status.items():
            status = info.get("status", "unknown")
            queries = info.get("queries_this_run", 0)
            key_lines.append(f"- **{label}**: {status} ({queries:,} queries)")
    else:
        key_lines.append("_No key status recorded for this run._")

    alert_lines: list[str] = []
    for label, info in metrics["exhausted"].items():
        msg = info.get("last_429_message", "quota exhausted (HTTP 429)")
        at = info.get("exhausted_at_utc", "unknown")
        alert_lines.append(f"- **{label}** exhausted at {at}: `{msg}`")
    for label, info in metrics["invalid"].items():
        msg = info.get("last_401_message", "invalid key (HTTP 401)")
        alert_lines.append(f"- **{label}** invalid: `{msg}`")

    sections: list[dict] = [
        {
            "activityTitle": "Run summary",
            "facts": facts,
            "markdown": True,
        },
        {
            "activityTitle": "API key status",
            "text": "\n".join(key_lines),
            "markdown": True,
        },
    ]

    if alert_lines:
        sections.append(
            {
                "activityTitle": "Alerts",
                "text": "\n".join(alert_lines),
                "markdown": True,
            }
        )

    if metrics["complete"]:
        sections.append(
            {
                "activityTitle": "Complete",
                "text": "All POIs in `texas.csv` have been geocoded.",
                "markdown": True,
            }
        )

    actions: list[dict] = []
    if metrics["download_url"]:
        actions.append(
            {
                "@type": "OpenUri",
                "name": "Download latest CSV",
                "targets": [{"os": "default", "uri": metrics["download_url"]}],
            }
        )
    if issue_url:
        actions.append(
            {
                "@type": "OpenUri",
                "name": "GitHub tracking issue",
                "targets": [{"os": "default", "uri": issue_url}],
            }
        )

    message: dict = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": "SafeGraph Texas Geocoding — Daily Progress",
        "themeColor": theme_color,
        "title": f"SafeGraph Texas Geocoding — {metrics['run_time']}",
        "sections": sections,
    }
    if actions:
        message["potentialAction"] = actions
    return message


def post_teams_message(webhook_url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8", errors="replace").strip()
        if body and body != "1":
            print(f"Teams webhook response: {body}")
    print("Posted Teams notification.")


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

    webhook_url = teams_webhook_url()
    if not webhook_url:
        print(
            "Teams notification skipped: set TEAMS_WEBHOOK_URL or teams_webhook_url "
            "to post the daily report to Microsoft Teams.",
            file=sys.stderr,
        )
        return

    issue_data = load_json(REPORT_ISSUE_JSON)
    issue_url = issue_data.get("issue_url")
    teams_payload = build_teams_message(progress, key_status, issue_url=issue_url)

    try:
        post_teams_message(webhook_url, teams_payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Teams webhook error ({exc.code}): {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Teams webhook error: {exc.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
