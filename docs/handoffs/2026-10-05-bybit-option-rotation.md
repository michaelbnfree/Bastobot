# Handoff: Bybit option-chain log rotation

From: Claude Code, 2026-10-05. For: Codex (owner of the Bybit collector, signal and dashboard).

## What changed
- New `/etc/logrotate.d/bastobot-bybit-options` rotates
  `/root/bastobot/data/bybit_options/btc_option_chain.jsonl` daily (00:00 UTC via `logrotate.timer`):
  gzip, keep 365 days, `dateext`, `delaycompress`.
- First rotation was forced at 05:52 UTC: 861 MB -> 84 MB (`btc_option_chain.jsonl-20261005.gz`,
  1,197 records, `gzip -t` OK). The live file restarted empty.
  Expect about 20 MB/day compressed (about 200 MB/day raw).
- `tools/bybit_option_collector.py` and `tools/paper_vol_dashboard.py` were not modified.
  `tools/bybit_forward_signal.py` was changed at the owner's request (freshness guard, empty-file
  fallback; see "Things to know").

## Things to know
1. Rotation empties the live file. `bybit_forward_signal.py` reads the newest snapshot in the same second the
   collector writes the next record, so the first tick after a rotation used to raise `IndexError`
   (happened once, 05:55 UTC on 2026-10-05; the 05:50 record has no row in `forward_vol_signals.jsonl`).
2. FIXED in `tools/bybit_forward_signal.py` (working tree, uncommitted, live via cron since 06:46 UTC):
   - `load_latest_snapshot()` reads the last record with a tail read (10 ms instead of loading the whole
     file), falls back to the newest rotated file (raw or `.gz`) when the live file is empty or missing, and
     raises `StaleSnapshotError` when the snapshot is older than 15 minutes (`MAX_SNAPSHOT_AGE_MS`; normal
     age is about 5 minutes, one missed collector tick is tolerated) or more than 60 s in the future.
   - On stale data the script writes no signal, prints `STALE-DATA: ...` to stderr and exits 2. Before this,
     a dead collector made it re-read the last record forever (the existing `rv_fresh` check only compared
     the candle data to the snapshot, never the snapshot to the wall clock).
   - 13 new tests in `tests/test_bybit_forward_signal.py` (12 fail on the old script).
3. The temporary postrotate "seed the new file with the last record" workaround was removed from the
   logrotate config because the signal no longer needs it (also removes the one-duplicate-per-day caveat).
   `delaycompress` stays so the newest rotated file is raw and the fallback is a cheap tail read.
4. `paper_vol_dashboard.py`'s `option_snapshots` now counts only the live file, so it resets daily. The
   dashboard still takes the last line of `forward_vol_signals.jsonl`, so a stale signal would look current
   there; it does not show data age.
5. Anything that needs history older than today must read the `.gz` files. Nothing does yet.

## Verify after the first scheduled rotation (2026-10-06 00:00 UTC)
Claude Code scheduled this check for 00:12 UTC (session-only; if that session is gone, do it by hand):
1. A `btc_option_chain.jsonl-20261006` file exists and the live file restarted small.
2. No new `IndexError` or `STALE-DATA` in `logs/bybit_forward_signal.log`.
3. The collector appended fresh records to the live file.
4. `forward_vol_signals.jsonl` advanced every 5 minutes across 00:00 (no missing tick).
5. `gzip -t` passes on `btc_option_chain.jsonl-20261005.gz` (the 20261006 file stays raw until the next rotation).
6. Disk use and the 365-day retention behave (`ls -la data/bybit_options`, `df -h /`).
7. The dashboard still answers and `option_snapshots` is the live-file count.

## State of this checkout
`tools/bybit_forward_signal.py` (live via cron from the working tree), `tests/test_bybit_forward_signal.py` and
this file were committed locally on the owner's instruction (not pushed unless the owner says so). The
logrotate config lives outside the repo at `/etc/logrotate.d/bastobot-bybit-options`. The rest of the
bastobot working tree still holds other uncommitted work that is not part of this change.

## Review notes (Codex review, checked by Claude Code) - both points are now resolved, see above
- The seed duplicates the previous day's final record into the new live file (one duplicate per day,
  spanning two files). Confirmed; harmless for the last-line readers, but it inflates a raw line count by 1.
- Stale seeded record if the collector fails: confirmed, but not new. `bybit_forward_signal.py` only
  checks that its candle data is fresh relative to the option snapshot (`rv_fresh`, `captured_ms - 2d`);
  it never compares the option snapshot's `captured_at` to wall-clock time, so a dead collector already
  made it re-read the last record before rotation existed. A snapshot-age guard belongs in the signal.
