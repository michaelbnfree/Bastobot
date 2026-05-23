#!/usr/bin/env python3
"""
Scheduled BTC snapshot — runs every 30 minutes via cron.
Two API calls 60s apart, validates data, logs to Notion.
"""

import sys
import os

sys.path.insert(0, '/root/bastobot')
os.chdir('/root/bastobot')

from dotenv import load_dotenv
load_dotenv('/root/bastobot/.env')

from skills.snapshot_logger import run_verified_snapshot

if __name__ == "__main__":
    text, flags = run_verified_snapshot(tag="scheduled")
    suspect = any("🚨" in f for f in flags)
    status = "SUSPECT" if suspect else (f"{len(flags)} flags" if flags else "clean")
    print(f"[DONE] status={status}")
