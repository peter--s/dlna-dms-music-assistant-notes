#!/usr/bin/env python3
"""Scan all forks of async_upnp_client for work on the DLNA media server (DMS) client.

Fetches upstream and every fork into a temporary bare repository, finds the commits that
are not in upstream, and flags those whose Python changes touch the ContentDirectory /
DmsDevice / DIDL-Lite code. Writes two CSV files:

  <out>/fork-branches.csv   one row per fork branch with commits not in upstream
  <out>/fork-commits.csv    the commits not in upstream whose diff matches the pattern

Usage:  python3 tools/fork_scan.py [out_dir]      (default: data)
Needs:  git, network access to github.com (one unauthenticated API call to list forks)
"""

import csv
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date
from pathlib import Path

UPSTREAM = "StevenLooman/async_upnp_client"
PATTERN = re.compile(
    r"DmsDevice|ContentDirectory|async_browse|async_search_directory|BrowseResult|TotalMatches|"
    r"RequestedCount|ServiceResetToken|SystemUpdateID|ContainerUpdateID|search_capabilities|"
    r"MediaServer|didl_lite|DIDL"
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    ).stdout


def list_forks() -> list[str]:
    forks, page = [], 1
    while True:
        url = f"https://api.github.com/repos/{UPSTREAM}/forks?per_page=100&page={page}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            batch = json.load(resp)
        forks += [f["full_name"] for f in batch]
        if len(batch) < 100:
            return forks
        page += 1


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    out.mkdir(parents=True, exist_ok=True)
    forks = list_forks()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "scan.git"
        subprocess.run(["git", "init", "-q", "--bare", str(repo)], check=True)
        git(repo, "remote", "add", "upstream", f"https://github.com/{UPSTREAM}.git")
        for full_name in forks:
            git(repo, "remote", "add", full_name.split("/")[0], f"https://github.com/{full_name}.git")
        remotes = git(repo, "remote").split()
        subprocess.run(["git", "-C", str(repo), "fetch", "-q", "--multiple", "--jobs=8", "--no-tags", *remotes],
                       check=False, env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})

        refs = [r for r in git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").split()
                if not r.startswith("refs/remotes/upstream/") and not r.endswith("/HEAD")]
        relevant: dict[str, int] = {}  # commit -> matching changed lines
        branches = []
        for ref in refs:
            commits = git(repo, "rev-list", ref, "--not", "--remotes=upstream").split()
            if not commits:
                continue
            hits = 0
            for commit in commits:
                if commit not in relevant:
                    diff = git(repo, "show", "--format=", "-U0", commit, "--", "*.py")
                    relevant[commit] = sum(
                        1 for line in diff.splitlines()
                        if line[:1] in "+-" and not line.startswith(("+++", "---")) and PATTERN.search(line)
                    )
                hits += relevant[commit] > 0
            fork, branch = ref.removeprefix("refs/remotes/").split("/", 1)
            branches.append([fork, branch, len(commits), git(repo, "log", "-1", "--format=%cs", ref).strip(), hits])

        with (out / "fork-branches.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["fork", "branch", "commits_not_in_upstream", "last_commit_date", "commits_touching_dms_code"])
            w.writerows(sorted(branches))

        with (out / "fork-commits.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["commit", "date", "author", "subject", "matching_changed_lines", "found_in_branches"])
            for commit, n in sorted(relevant.items(), key=lambda kv: -kv[1]):
                if not n:
                    continue
                meta = git(repo, "log", "-1", "--format=%cs%x1f%an%x1f%s", commit).strip().split("\x1f")
                where = sorted({r.removeprefix("refs/remotes/") for r in refs
                                if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, r],
                                                  capture_output=True).returncode == 0})
                w.writerow([commit[:12], meta[0], meta[1], meta[2], n, " ".join(where)])

    print(f"{date.today()}: {len(forks)} forks, {len(branches)} branches with commits not in upstream, "
          f"{len(relevant)} such commits, {sum(1 for n in relevant.values() if n)} touching DMS/DIDL code -> {out}/")


if __name__ == "__main__":
    main()
