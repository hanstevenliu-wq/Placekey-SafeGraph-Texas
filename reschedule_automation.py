"""
Advance the daily geocoding schedule by one hour after each run.

Updates .cursor/automation.json and the GitHub Actions workflow cron so the
next run is delayed, giving Placekey rolling-24h quotas more time to refresh.

Optional: set CURSOR_API_KEY to attempt updating the Cursor automation via API.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
AUTOMATION_JSON = ROOT / ".cursor" / "automation.json"
WORKFLOW_YML = ROOT / ".github" / "workflows" / "trigger-daily-geocode.yml"

CRON_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$"
)


def load_schedule() -> dict:
    if not AUTOMATION_JSON.exists():
        raise FileNotFoundError(f"Missing {AUTOMATION_JSON}")
    return json.loads(AUTOMATION_JSON.read_text())


def bump_cron_hour(cron: str) -> str:
    match = CRON_RE.match(cron.strip())
    if not match:
        raise ValueError(f"Unsupported cron format (expected 5 fields): {cron!r}")
    minute, hour, dom, month, dow = match.groups()
    if not hour.isdigit():
        raise ValueError(f"Hour field must be numeric to auto-reschedule: {cron!r}")
    next_hour = (int(hour) + 1) % 24
    return f"{minute} {next_hour} {dom} {month} {dow}"


def update_workflow_cron(cron: str) -> bool:
    if not WORKFLOW_YML.exists():
        return False
    text = WORKFLOW_YML.read_text()
    updated, count = re.subn(
        r"(cron:\s*['\"])([^'\"]+)(['\"])",
        rf"\g<1>{cron}\g<3>",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError(f"Could not update cron in {WORKFLOW_YML}")
    WORKFLOW_YML.write_text(updated)
    return True


def try_cursor_api(automation_id: str, cron: str) -> None:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        return

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"schedule": {"cron": cron}}
    base = "https://api.cursor.com"
    paths = [
        f"/v1/automations/{automation_id}",
        f"/v1/automations/{automation_id}/schedule",
        f"/v0/automations/{automation_id}",
    ]
    for path in paths:
        for method in ("PATCH", "PUT"):
            try:
                response = requests.request(
                    method,
                    f"{base}{path}",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
            except requests.RequestException as exc:
                print(f"Cursor API {method} {path}: {exc}", file=sys.stderr)
                continue
            if response.status_code in (200, 204):
                print(f"Updated Cursor automation schedule via {method} {path}")
                return
            if response.status_code not in (404, 405, 501):
                print(
                    f"Cursor API {method} {path}: HTTP {response.status_code} "
                    f"{response.text[:300]}",
                    file=sys.stderr,
                )


def git_commit_schedule(cron: str, automation_id: str) -> None:
    subprocess.run(["git", "add", str(AUTOMATION_JSON)], check=True, cwd=ROOT)
    if WORKFLOW_YML.exists():
        subprocess.run(["git", "add", str(WORKFLOW_YML)], check=True, cwd=ROOT)

    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
        capture_output=True,
    )
    if status.returncode == 0:
        print("Schedule unchanged; nothing to commit.")
        return

    message = f"chore: reschedule daily geocoding to {cron} UTC (automation {automation_id[:8]}…)"
    subprocess.run(["git", "commit", "-m", message], check=True, cwd=ROOT)
    push = subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT)
    if push.returncode != 0:
        print("git push failed; schedule committed locally only.", file=sys.stderr)
        sys.exit(push.returncode)
    print(f"Committed and pushed next schedule: {cron}")


def main() -> None:
    data = load_schedule()
    old_cron = data.get("cron", "").strip()
    if not old_cron:
        print("No cron in automation.json", file=sys.stderr)
        sys.exit(1)

    new_cron = bump_cron_hour(old_cron)
    data["cron"] = new_cron
    data["last_rescheduled_utc"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    data["previous_cron"] = old_cron
    AUTOMATION_JSON.write_text(json.dumps(data, indent=2) + "\n")

    workflow_updated = update_workflow_cron(new_cron)
    automation_id = data.get("automation_id", "")
    if automation_id:
        try_cursor_api(automation_id, new_cron)

    print(f"Schedule: {old_cron} -> {new_cron} (UTC)")
    if workflow_updated:
        print(f"Updated {WORKFLOW_YML.relative_to(ROOT)}")
    else:
        print("No workflow file to update.")

    if os.environ.get("GIT_COMMIT_SCHEDULE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    ):
        git_commit_schedule(new_cron, automation_id or "unknown")


if __name__ == "__main__":
    main()
