#!/usr/bin/env python3
"""
Daily commit of data/snapshots.jsonl to GitHub.
Runs at midnight UTC via cron.
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = "/root/bastobot"
JSONL = Path(f"{REPO}/data/snapshots.jsonl")


def run(cmd, **kwargs):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, **kwargs)


if __name__ == "__main__":
    if not JSONL.exists() or JSONL.stat().st_size == 0:
        print("[DAILY] No snapshot data to commit — skipping")
        sys.exit(0)

    # Count new lines since last commit
    diff = run(["git", "diff", "--stat", "data/snapshots.jsonl"])
    if "snapshots.jsonl" not in diff.stdout:
        print("[DAILY] No changes to snapshots.jsonl — skipping")
        sys.exit(0)

    # Count entries added today
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count = sum(1 for line in JSONL.read_text().splitlines() if today in line)

    run(["git", "add", "data/snapshots.jsonl"])
    msg = f"data: BTC snapshots {today} ({count} entries)"
    result = run(["git", "commit", "-m", msg])
    if result.returncode != 0:
        print(f"[DAILY] Commit failed: {result.stderr}")
        sys.exit(1)

    push = run(["git", "push"])
    if push.returncode != 0:
        print(f"[DAILY] Push failed: {push.stderr}")
        sys.exit(1)

    print(f"[DAILY] Committed and pushed: {msg}")
