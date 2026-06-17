---
title: CASSANDRA
emoji: 🛰️
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# CASSANDRA — Accounting-Manipulation Detection System

> A point-in-time forensic intelligence engine. It ingests a company's *as-filed* SEC
> filings and emits (1) a calibrated per-filing manipulation-risk score and (2) an
> analyst-actionable evidence dossier with benign counter-arguments and historical analogues.

This repository is a **working implementation of all five phases** of the architecture
blueprint — not a mock. Every number traces to a real SEC filing; the agent layer argues
both sides and cites its evidence; the model is evaluated under strict no-look-ahead
discipline. The brand is *intellectual honesty + point-in-time hygiene*.

---

## What runs today (end to end, on real data)

```
ingest (real SEC EDGAR, PIT XBRL)  →  forensic + Benford + text + graph features
   →  late-fusion calibrated score  →  agentic review (LangGraph-topology)  →  dossier
   →  FastAPI (SSE)  →  Next.js analyst workstation
```

**Hero validation (point-in-time, trained on nothing):** scored on its FY2015 10-K — the
exact year the SEC charged it with pulling revenue forward — **Under Armour lands 0.85
ELEVATED** (Beneish M = −0.90 crossing the −1.78 threshold, Dechow F = 1.94, CFO/NI = −0.19,
accruals/TA +0.096). Its FY2014 filing scores **0.33 LOW**. The system flags the fraud year
and clears the year before.

**Backtest (honest, small-sample):** on 1,755 firm-years / 114 firms / 73 positive
firm-years (4.2% base rate), a class-weighted GBM tabular tower reaches **PR-AUC 0.159 vs
0.062 for the Beneish M baseline and 0.047 for Dechow F** — ~2.5× the classic forensic
thresholds, with P@10 = 0.50 (5× the baselines). Fusion lifts top-decile lift to ~4.1×.
Consistent with the literature, the auxiliary towers (text/graph) do not yet beat tabular on
PR-AUC at this sample size — a documented research gap, shown plainly in the ablation table.

---

## Phase map (blueprint → code)

| Phase | Blueprint | Where |
|---|---|---|
| 1 — Ingestion & medallion | EDGAR crawler, PIT XBRL, bronze/silver/gold, label alignment | `cassandra/ingest/`, `cassandra/lake/`, `cassandra/labels/` |
| 2 — Features | forensic battery, Benford, text (LM + LSA), graph (auditor) | `cassandra/features/` |
| 3 — Models | 4 towers, OOF late fusion, isotonic calibration, backtest + ablation | `cassandra/model/` |
| 4 — Agents | 6 specialists + challenger + analogue + synthesis, LangGraph, cost gating | `cassandra/agents/` |
| 5 — Serving & UI | FastAPI + SSE, Next.js workstation, portfolio/eval views | `cassandra/api/`, `frontend/` |

Point-in-time invariants enforced throughout: features are built from the **original 10-K**
facts (amendments excluded), positive labels are aligned to the **commission period** (not
the enforcement date), and the temporal tower only sees filings up to the scored year.

---

## Quick start

```bash
# 0) Python deps (Anaconda already has most; lightgbm + langgraph are the extras)
pip install -r requirements.txt
pip install lightgbm langgraph        # optional but used by Phases 3 & 4

# 1) Score one filing end-to-end from the terminal (no setup needed)
python scripts/demo.py UAA --year 2015      # the hero case
python scripts/demo.py AAPL                  # a clean large-cap

# 2) Build the modeling universe into the medallion lake (~6 min, real SEC pulls)
python scripts/build_universe.py             # ingest positives + clean sample -> gold table

# 3) Train the four towers + run the §7 backtest/ablation
python scripts/train_models.py               # writes data/models/report.json

# 4) Serve the API + analyst workstation
./run.sh                                      # FastAPI on :8011 (serves a self-contained UI too)
#   …or the full Next.js workstation:
cd frontend && npm install && npm run dev     # Next.js on :3000  (talks to :8011)
```

The **agent layer runs with zero external dependencies** (deterministic, evidence-grounded
rules). Set `ANTHROPIC_API_KEY` to light up the LLM path (the §6.4 prompt templates) — the
output schema is identical either way.

---

## Coverage & autonomy

- **Any U.S. registrant.** Search/resolve works across the entire EDGAR universe (~800k CIKs),
  not just ticker-listed firms — by ticker, company name, or raw CIK (incl. foreign private
  issuers filing 20-F). Listed companies autocomplete instantly; anything else resolves via
  EDGAR company search. Truly foreign-only filers (no EDGAR presence) remain out of scope (§3.5).

- **The Sentinel — autonomous, continuous flagging.** A self-running agent scans newly-filed
  SEC reports (the EDGAR daily-index firehose), cheap-scores every filer, escalates the top-k
  riskiest to a full agent dossier (cost gating §6.6), and writes irregularity alerts to the
  lake — idempotently, so it runs forever on a schedule.

  ```bash
  python scripts/sentinel.py --once                  # one scan of the latest filings (cron-friendly)
  python scripts/sentinel.py --loop --interval 3600  # run forever, poll hourly
  # unattended: 0 * * * * cd /path/to/CASSANDRA && python scripts/sentinel.py --once
  ```
  Scale-out is by fanning the `--date`/sector axis across workers and raising `--limit`; the
  expensive LLM/agent step stays bounded by `--topk`.

- **The watchdog map.** The **Sentinel** tab renders a live US map: a drone sweeps the country
  (`/api/sentinel/stream` SSE), plotting each filer at its SEC-registered HQ the instant it is
  scored, locking onto elevated detections with a target reticle. Click any target for a
  one-click **dossier PDF** (`/api/dossier.pdf?q=<cik>`) — a branded, audit-grade report of
  exactly which signals fired, the evidence, and the good-faith counter-argument.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/search?q=` | ticker / name / CIK autocomplete — any SEC registrant |
| `GET /api/analyze?q=&year=` | full analysis summary (features + calibrated score) |
| `GET /api/score/stream?q=&year=` | **SSE** — live agent-graph events, then the dossier |
| `GET /api/eval` | Phase-3 backtest + ablation report |
| `GET /api/screen?k=` | cost-gated triage screen of the lake universe |
| `GET /api/alerts?limit=` | Sentinel irregularity feed (highest risk first) |
| `GET /api/sentinel/scan?source=daily&limit=` | trigger one autonomous scan |

---

## Honest scope & limitations

- **Labels are scarce.** The seed + verified label set is tens of positive firm-years, so
  absolute metrics carry wide intervals. The deliverable is the *protocol* (PIT, group-aware,
  walk-forward) and the *relative lift* over baselines — exactly what §7 specifies.
- **The runtime scorer is a transparent, literature-anchored evidence combiner** (Phase-0
  stand-in). The trained four-tower model (Phase 3) is a separate artifact surfaced in the
  eval view; both share the same interface.
- **Text/graph towers are runnable proxies** (Loughran-McDonald + LSA; auditor graph), not
  the production FinBERT/GNN. They are weighted modestly and labelled as such — no overselling.
- **International heroes (Wirecard, Steinhoff, Luckin) are out-of-distribution** for the
  US-GAAP/XBRL scorer and are used as qualitative pattern analogues only (§3.5).

See `cassandra/` module docstrings for the per-component specifications and the exact
operationalizations behind each forensic formula.
