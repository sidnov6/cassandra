#!/usr/bin/env python3
"""Build the modeling universe into the medallion lake.

    python scripts/build_universe.py            # full default universe
    python scripts/build_universe.py --limit 8  # quick smoke test (first 8)
    python scripts/build_universe.py --no-text  # skip auditor/text (faster)

Positives = XBRL-era U.S. cases from the label set; negatives = a diverse presumed-clean
large/mid-cap sample. Emits gold_firm_filing_features for Phase-3 training.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cassandra.labels.known_cases import load_cases  # noqa: E402
from cassandra.lake.build import build_universe  # noqa: E402
from cassandra.lake.store import MedallionStore  # noqa: E402

CLEAN_SAMPLE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "JNJ", "PG", "KO", "PEP",
    "WMT", "COST", "HD", "MCD", "NKE", "DIS", "V", "MA", "JPM", "BAC",
    "XOM", "CVX", "UNH", "PFE", "MRK", "ABBV", "TMO", "ACN", "CSCO", "INTC",
    "ORCL", "IBM", "TXN", "QCOM", "AMD", "ADBE", "CRM", "CAT", "DE", "BA",
    "HON", "MMM", "UPS", "FDX", "LMT", "RTX", "VZ", "NFLX", "SBUX", "TGT",
    "LOW", "CL", "KMB", "GIS", "ADP", "INTU", "AMAT", "MU", "GILD", "AMGN",
    "BMY", "CVS", "SPGI", "GS", "MS", "AXP", "BLK", "SO", "NEE", "DUK",
    "EMR", "ITW", "ETN", "GD", "NOC", "SYY", "K", "ROK", "PH", "USB",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-text", action="store_true")
    args = ap.parse_args()

    # XBRL-era US positives from the (verified-merged) label set. Use CIK when available —
    # many fraud filers are delisted and resolve more reliably by CIK than by stale ticker.
    pos = [(c.cik or c.ticker) for c in load_cases() if c.sec_xbrl and (c.cik or c.ticker)]
    universe = list(dict.fromkeys(pos + CLEAN_SAMPLE))  # dedupe, preserve order
    if args.limit:
        universe = universe[:args.limit]

    print(f"Universe: {len(universe)} companies ({len(pos)} labelled positives in seed)")
    t0 = time.time()

    def progress(i, n, q):
        print(f"  [{i+1:>3}/{n}] {q:<8}", end="\r", flush=True)

    summary = build_universe(universe, store=MedallionStore(),
                             with_text=not args.no_text, progress=progress)
    print("\n\n=== BUILD SUMMARY ===")
    for k, v in summary.items():
        if k == "tables":
            print("  tables:")
            for t, meta in v.items():
                print(f"    {t:30} {meta['rows']:>6} rows  v{meta['versions']}  ({meta['layer']})")
        else:
            print(f"  {k:22} {v}")
    print(f"  elapsed                {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
