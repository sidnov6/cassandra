#!/usr/bin/env python3
"""CASSANDRA Sentinel — autonomous, continuous irregularity flagging.

    python scripts/sentinel.py --once                      # one scan of the latest filings
    python scripts/sentinel.py --once --source watchlist   # rescan the tracked universe
    python scripts/sentinel.py --loop --interval 3600      # run forever, poll hourly
    python scripts/sentinel.py --once --date 2026-06-16    # a specific index day

For true unattended operation, schedule the --once form (cron / systemd / launchd), e.g.
    0 * * * *  cd /path/to/CASSANDRA && python scripts/sentinel.py --once
Each run is idempotent (deduped on accession), so overlapping schedules are safe.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cassandra.monitor import Sentinel  # noqa: E402


def _run(sentinel: Sentinel, args) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    summ = sentinel.scan(on=args.date, source=args.source, limit=args.limit,
                         topk=args.topk, stamp=stamp)
    s = summ.to_dict()
    print(f"[{stamp}] scan {s['source']}/{s['index_date']}: "
          f"{s['candidates']} candidates → {s['scored']} scored → {s['flagged']} flagged "
          f"({s['agent_reviewed']} agent-reviewed, {s['elevated']} elevated, {s['new_alerts']} new)")
    df = sentinel.alerts(8)
    for _, r in (df.iterrows() if not df.empty else []):
        tag = "AGENT" if r["agent_reviewed"] else "     "
        print(f"    {r['score']:.2f} {r['band']:8} {tag} {str(r['ticker'] or r['cik'])[:8]:8} "
              f"{str(r['company'])[:30]:30} {str(r['top_flags'])[:40]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="CASSANDRA autonomous Sentinel")
    ap.add_argument("--once", action="store_true", help="single scan then exit (for cron)")
    ap.add_argument("--loop", action="store_true", help="run continuously")
    ap.add_argument("--interval", type=int, default=3600, help="loop poll interval (seconds)")
    ap.add_argument("--source", choices=["daily", "watchlist"], default="daily")
    ap.add_argument("--date", default=None, help="EDGAR index date YYYY-MM-DD (daily source)")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--topk", type=int, default=8, help="how many get the full agent dossier")
    args = ap.parse_args()

    sentinel = Sentinel()
    if args.loop:
        print(f"Sentinel running — polling {args.source} every {args.interval}s. Ctrl-C to stop.")
        while True:
            try:
                _run(sentinel, args)
            except KeyboardInterrupt:
                print("\nSentinel stopped."); return 0
            except Exception as e:
                print(f"  scan error: {e}")
            time.sleep(args.interval)
    else:
        _run(sentinel, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
