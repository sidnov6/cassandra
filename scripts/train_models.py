#!/usr/bin/env python3
"""Train the four towers + fusion + calibration and run the §7 backtest/ablation.

    python scripts/train_models.py            # uses cached gold + text
    python scripts/train_models.py --no-text  # tabular/graph/temporal only

Reads gold_firm_filing_features from the lake, builds the text-tower dataset from cached
10-K text, trains, evaluates, and writes data/models/report.json (consumed by the eval UI).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from cassandra.features.embeddings import lexical_features  # noqa: E402
from cassandra.features.text import strip_html  # noqa: E402
from cassandra.ingest.edgar import EdgarClient  # noqa: E402
from cassandra.lake.store import MedallionStore  # noqa: E402
from cassandra.model.train import train_and_evaluate  # noqa: E402


def build_text_df(gold: pd.DataFrame, client: EdgarClient) -> pd.DataFrame:
    rows = []
    for cik in gold["cik"].astype(str).unique():
        try:
            filings = client.recent_filings(cik, forms=("10-K",), limit=10)
            latest = next((f for f in filings if not f["is_amendment"] and f.get("primary_doc")), None)
            if not latest:
                continue
            html = client.filing_text(cik, latest["accession"], latest["primary_doc"])
            text = strip_html(html)
            if len(text) < 1000:
                continue
            rows.append({"cik": cik, **lexical_features(text)})
        except Exception:
            continue
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-text", action="store_true")
    args = ap.parse_args()

    gold = MedallionStore().read("gold_firm_filing_features")
    if gold is None or gold.empty:
        print("No gold table. Run scripts/build_universe.py first.")
        return 1
    print(f"Gold: {len(gold)} firm-years · {gold['cik'].nunique()} firms · "
          f"{int(gold['label'].sum())} positive firm-years")

    text_df = None
    if not args.no_text:
        print("Building text-tower dataset from cached 10-K text …")
        text_df = build_text_df(gold, EdgarClient())
        print(f"  text features for {len(text_df)} firms")

    print("Training towers + fusion + calibration, evaluating …")
    report = train_and_evaluate(gold, text_df)

    print("\n=== EVALUATION REPORT ===")
    print(f"  rows={report['n_rows']}  firms={report['n_firms']}  "
          f"positives={report['positives']}  base_rate={report['base_rate']:.3f}")
    print("\n  Per-tower OOF PR-AUC:")
    for t, v in report["tower_oof_pr_auc"].items():
        print(f"    {t:12} {v:.3f}")
    print("\n  ABLATION (PR-AUC / P@10 / top-decile lift):")
    for name, mm in report["ablation"].items():
        print(f"    {name:36} PR-AUC {mm['pr_auc']:.3f}   "
              f"P@10 {mm['precision_at_k'].get('10',0):.2f}   lift {mm['top_decile_lift']:.2f}")
    if report["walk_forward"]:
        print("\n  WALK-FORWARD (expanding window):")
        for w in report["walk_forward"]:
            print(f"    test FY{w['test_year']}  n={w['n_test']:>3}  pos={w['positives']:>2}  "
                  f"PR-AUC {w['pr_auc']:.3f}")
    print(f"\n  base rate {report['base_rate']:.3f}  →  models + report saved to data/models/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
