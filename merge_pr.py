"""
Create and merge a pull request for the current branch into main.

Used after automation runs that change code on a feature branch. Falls back to
a direct git merge + push when the GitHub integration token cannot open PRs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_REPO = os.environ.get("GITHUB_REPO", "hanstevenliu-wq/Placekey-SafeGraph-Texas")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def github_token() -> str:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "CURSOR_GITHUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    try:
        result = run("gh", "auth", "token", check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return ""


def current_branch() -> str:
    result = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip()


def has_commits_ahead_of_main(branch: str) -> bool:
    run("git", "fetch", "origin", "main", check=False)
    result = run(
        "git", "rev-list", "--count", f"origin/main..{branch}", check=False
    )
    if result.returncode != 0:
        result = run("git", "rev-list", "--count", f"main..{branch}", check=False)
    return result.returncode == 0 and int(result.stdout.strip() or "0") > 0


def working_tree_clean() -> bool:
    result = run("git", "status", "--porcelain", check=False)
    return result.returncode == 0 and not result.stdout.strip()


def github_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "placekey-safegraph-texas",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def merge_via_api(token: str, repo: str, branch: str) -> bool:
    owner, name = repo.split("/", 1)
    base = "main"

    pr_list_url = (
        f"https://api.github.com/repos/{owner}/{name}/pulls"
        f"?head={owner}:{branch}&base={base}&state=open"
    )
    try:
        existing = github_request("GET", pr_list_url, token)
    except urllib.error.HTTPError as exc:
        print(f"Could not list PRs: {exc.read().decode()}", file=sys.stderr)
        return False

    if existing:
        pr_number = int(existing[0]["number"])
        print(f"Using existing PR #{pr_number}")
    else:
        create_url = f"https://api.github.com/repos/{owner}/{name}/pulls"
        title = f"Merge {branch} (daily automation)"
        body = "Automated merge of daily geocoding / schedule updates."
        try:
            pr = github_request(
                "POST",
                create_url,
                token,
                {"title": title, "head": branch, "base": base, "body": body},
            )
        except urllib.error.HTTPError as exc:
            print(f"Could not create PR: {exc.read().decode()}", file=sys.stderr)
            return False
        pr_number = int(pr["number"])
        print(f"Created PR #{pr_number}: {pr.get('html_url')}")

    merge_url = f"https://api.github.com/repos/{owner}/{name}/pulls/{pr_number}/merge"
    try:
        result = github_request(
            "PUT",
            merge_url,
            token,
            {"merge_method": "merge", "commit_title": f"Merge {branch} (automation)"},
        )
    except urllib.error.HTTPError as exc:
        print(f"Could not merge PR: {exc.read().decode()}", file=sys.stderr)
        return False

    if result.get("merged"):
        print(f"Merged PR #{pr_number} into {base}")
        return True
    print(f"Merge not completed: {result}", file=sys.stderr)
    return False


def merge_via_git(branch: str) -> None:
    run("git", "fetch", "origin", "main")
    run("git", "checkout", "main")
    run("git", "pull", "origin", "main")
    merge = run("git", "merge", branch, "-m", f"Merge {branch} (automation)", check=False)
    if merge.returncode != 0:
        print(merge.stderr or merge.stdout, file=sys.stderr)
        sys.exit(merge.returncode)
    push = run("git", "push", "origin", "main", check=False)
    if push.returncode != 0:
        print(push.stderr or push.stdout, file=sys.stderr)
        sys.exit(push.returncode)
    print(f"Merged {branch} into main via git and pushed.")


def main() -> None:
    branch = os.environ.get("MERGE_BRANCH", "").strip() or current_branch()
    if branch == "main":
        if working_tree_clean():
            print("On main with a clean tree; nothing to merge.")
            return
        branch = current_branch()
        if branch == "main":
            print("Commit changes on a branch before calling merge_pr.py", file=sys.stderr)
            sys.exit(1)

    if not has_commits_ahead_of_main(branch):
        print(f"No commits on {branch} ahead of main; nothing to merge.")
        return

    run("git", "push", "-u", "origin", branch, check=False)

    token = github_token()
    if token and merge_via_api(token, DEFAULT_REPO, branch):
        run("git", "checkout", branch, check=False)
        return

    print("PR API merge unavailable; falling back to git merge.", file=sys.stderr)
    merge_via_git(branch)
    run("git", "checkout", branch, check=False)


if __name__ == "__main__":
    main()
