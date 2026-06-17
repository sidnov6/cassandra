#!/usr/bin/env python3
"""CASSANDRA CLI — score a filing end to end and print the dossier.

    python scripts/demo.py UAA --year 2015
    python scripts/demo.py AAPL
    python scripts/demo.py "Under Armour"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cassandra.agents.orchestrator import stream_agent_graph  # noqa: E402
from cassandra.pipeline import build_analysis  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="CASSANDRA forensic triage")
    ap.add_argument("query", help="ticker, company name, or CIK")
    ap.add_argument("--year", type=int, default=None, help="fiscal year (point-in-time)")
    ap.add_argument("--no-text", action="store_true", help="skip the text tower")
    args = ap.parse_args()

    print(f"\n  Resolving and ingesting {args.query!r} from SEC EDGAR …", flush=True)
    ctx = build_analysis(args.query, target_year=args.year, with_text=not args.no_text)
    s = ctx.score

    print(f"\n  {ctx.panel.entity}  ·  CIK {ctx.ref.cik}  ·  FY{ctx.forensic.fiscal_year}"
          f"  ·  accession {ctx.accession}")
    print(f"  point-in-time: {ctx.target_fye}  (as-filed, amendments excluded)\n")
    print("  ── FORENSIC BATTERY " + "─" * 40)
    for k in ("beneish", "altman", "dechow", "accruals", "benford"):
        print(f"   • {ctx.forensic.interpretations[k]}")

    print("\n  ── CALIBRATED RISK " + "─" * 41)
    bar = int(s.calibrated_p * 30)
    print(f"   score {s.calibrated_p:.2f}  [{'█'*bar}{'·'*(30-bar)}]  {s.band}  "
          f"(confidence {s.confidence:.2f})")
    print("   contributions: " + "  ".join(f"{k} {v:.0%}" for k, v in
          sorted(s.contributions.items(), key=lambda t: -t[1])))

    print("\n  ── AGENT GRAPH " + "─" * 45)
    dossier = {}
    for ev in stream_agent_graph(ctx.agent_ctx(), s.to_dict()):
        if ev["node"] == "__final__":
            dossier = ev["payload"]["dossier"]
        elif ev["status"] == "done" and ev["msg"]:
            print(f"   ▸ {ev['node']:11} {ev['msg']}")

    print("\n  ── DOSSIER " + "─" * 49)
    print("\n".join("   " + ln for ln in dossier["memo"].splitlines()))
    print(f"\n  (agent mode: {dossier['llm_mode']})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
