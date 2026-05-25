"""
Upload geocoded_results.csv to a GitHub Release for download.

Maintains a rolling release tagged geocoded-results-latest with the cumulative
CSV attached. Also creates a dated snapshot release when new rows were saved.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_CSV = ROOT / "geocoded_results.csv"
PROGRESS_JSON = OUTPUT_DIR / "progress.json"
RELEASE_JSON = OUTPUT_DIR / "release.json"

LATEST_TAG = "geocoded-results-latest"
ASSET_NAME = "geocoded_results.csv"
DEFAULT_REPO = os.environ.get("GITHUB_REPO", "hanstevenliu-wq/Placekey-SafeGraph-Texas")


def github_token() -> str:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "CURSOR_GITHUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def github_request(
    method: str,
    url: str,
    token: str,
    payload: dict | None = None,
    *,
    accept: str = "application/vnd.github+json",
) -> dict | list:
    data = None
    headers = {
        "Accept": accept,
        "User-Agent": "placekey-safegraph-texas",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def repo_urls(repo: str) -> tuple[str, str, str, str]:
    owner, name = repo.split("/", 1)
    api_base = f"https://api.github.com/repos/{owner}/{name}"
    web_base = f"https://github.com/{owner}/{name}"
    return owner, name, api_base, web_base


def count_data_rows() -> int:
    if not OUTPUT_CSV.exists():
        return 0
    df = pd.read_csv(OUTPUT_CSV, dtype=str)
    if df.empty:
        return 0
    if "placekey" in df.columns:
        success = df["placekey"].notna() & (df["placekey"].astype(str).str.strip() != "")
        return int(success.sum())
    return len(df)


def load_progress() -> dict:
    if not PROGRESS_JSON.exists():
        return {}
    return json.loads(PROGRESS_JSON.read_text())


def get_release_by_tag(token: str, api_base: str, tag: str) -> dict | None:
    url = f"{api_base}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    try:
        return github_request("GET", url, token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def delete_release_assets(token: str, api_base: str, release: dict) -> None:
    for asset in release.get("assets", []):
        asset_id = asset.get("id")
        if not asset_id:
            continue
        url = f"{api_base}/releases/assets/{asset_id}"
        github_request("DELETE", url, token)


def upload_release_asset(token: str, upload_url: str, file_path: Path, name: str) -> dict:
    query = urllib.parse.urlencode({"name": name})
    url = upload_url.split("{", 1)[0] + "?" + query
    data = file_path.read_bytes()
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "User-Agent": "placekey-safegraph-texas",
        "Content-Length": str(len(data)),
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def create_release(
    token: str,
    api_base: str,
    *,
    tag: str,
    name: str,
    body: str,
) -> dict:
    url = f"{api_base}/releases"
    return github_request(
        "POST",
        url,
        token,
        {
            "tag_name": tag,
            "target_commitish": os.environ.get("RELEASE_TARGET_BRANCH", "main"),
            "name": name,
            "body": body,
            "draft": False,
            "prerelease": False,
        },
    )


def update_release(token: str, api_base: str, release_id: int, *, body: str, name: str) -> dict:
    url = f"{api_base}/releases/{release_id}"
    return github_request("PATCH", url, token, {"name": name, "body": body})


def publish_tagged_release(
    token: str,
    repo: str,
    *,
    tag: str,
    title: str,
    body: str,
) -> dict:
    _, _, api_base, web_base = repo_urls(repo)
    release = get_release_by_tag(token, api_base, tag)
    if release is None:
        release = create_release(token, api_base, tag=tag, name=title, body=body)
    else:
        delete_release_assets(token, api_base, release)
        release = update_release(
            token,
            api_base,
            int(release["id"]),
            name=title,
            body=body,
        )

    asset = upload_release_asset(token, release["upload_url"], OUTPUT_CSV, ASSET_NAME)
    download_url = f"{web_base}/releases/download/{tag}/{ASSET_NAME}"
    return {
        "tag": tag,
        "release_id": release["id"],
        "release_url": release.get("html_url"),
        "download_url": download_url,
        "asset_url": asset.get("browser_download_url"),
        "asset_size_bytes": asset.get("size"),
    }


def save_release_info(info: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RELEASE_JSON.write_text(json.dumps(info, indent=2))


def main() -> None:
    token = github_token()
    if not token:
        print(
            "Set GITHUB_TOKEN (or GH_TOKEN / CURSOR_GITHUB_TOKEN) to publish releases.",
            file=sys.stderr,
        )
        sys.exit(1)

    data_rows = count_data_rows()
    if data_rows == 0:
        print("No geocoded rows to publish; skipping GitHub release upload.")
        return

    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO
    progress = load_progress()
    saved_this_run = int(progress.get("saved_this_run", 0))
    run_time = progress.get("last_run_utc", pd.Timestamp.now("UTC").isoformat())
    completed = int(progress.get("completed_rows", data_rows))
    total = int(progress.get("total_rows", data_rows))

    latest_body = (
        "Cumulative SafeGraph Texas geocoding results from the daily Placekey automation.\n\n"
        f"- Successful rows: {data_rows:,}\n"
        f"- Completed POIs: {completed:,} / {total:,}\n"
        f"- Last updated (UTC): {run_time}\n\n"
        f"Download `{ASSET_NAME}` below."
    )

    try:
        latest = publish_tagged_release(
            token,
            repo,
            tag=LATEST_TAG,
            title="Geocoded results (latest)",
            body=latest_body,
        )
        print(f"Published latest release: {latest['download_url']}")

        info = {
            "latest": latest,
            "published_at_utc": pd.Timestamp.now("UTC").isoformat(),
            "data_rows": data_rows,
        }

        if saved_this_run > 0:
            date_tag = f"geocode-{pd.Timestamp.now('UTC').strftime('%Y-%m-%d')}"
            dated_body = (
                f"Daily snapshot from the SafeGraph Texas geocoding run on {run_time}.\n\n"
                f"- Rows saved this run: {saved_this_run:,}\n"
                f"- Cumulative successful rows in file: {data_rows:,}\n"
            )
            dated = publish_tagged_release(
                token,
                repo,
                tag=date_tag,
                title=f"Geocoded results — {date_tag.removeprefix('geocode-')}",
                body=dated_body,
            )
            info["dated"] = dated
            print(f"Published dated snapshot: {dated['download_url']}")

        save_release_info(info)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"GitHub release error ({exc.code}): {detail}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
