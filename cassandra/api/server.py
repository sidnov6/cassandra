"""CASSANDRA scoring API (blueprint §5.5).

Endpoints
  GET /api/health                      -> liveness + LLM mode
  GET /api/search?q=...                -> company autocomplete (ticker / name / CIK)
  GET /api/analyze?q=...&year=...      -> full analysis summary (features + score), no agents
  GET /api/score/stream?q=...&year=... -> SSE: live agent-graph events, then the dossier
  GET /api/portfolio?tickers=a,b,c     -> ranked risk list (Precision@k-style triage view)
  GET /                                -> the analyst workstation (static HTML)

The SSE stream is what powers the live "Agentic Reasoning Journey" — node activations and
thinking traces arrive in real time as the graph executes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ..agents.orchestrator import GRAPH_NODES, stream_agent_graph
from ..config import LLM_ENABLED, LLM_MODEL, LLM_PROVIDER
from ..ingest.edgar import EdgarClient
from ..pipeline import build_analysis

from ..config import ROOT
_EXPORT = ROOT / "frontend" / "out"   # static Next.js export, served on the same origin as /api

app = FastAPI(title="CASSANDRA", version="0.1.0")
# Allow the Next.js dev server (different port) to call the API + consume the SSE stream.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
_client = EdgarClient()
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_mode": "llm" if LLM_ENABLED else "deterministic",
            "llm_provider": LLM_PROVIDER, "llm_model": LLM_MODEL if LLM_ENABLED else None,
            "graph_nodes": GRAPH_NODES}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = 10):
    refs = _client.search(q, limit=limit)
    return {"results": [{"cik": r.cik, "ticker": r.ticker, "name": r.title} for r in refs]}


@app.get("/api/analyze")
def analyze(q: str, year: Optional[int] = None, text: bool = True):
    try:
        ctx = build_analysis(q, target_year=year, with_text=text, client=_client)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return ctx.summary()


@app.get("/api/score/stream")
def score_stream(q: str, year: Optional[int] = None, text: bool = True):
    def gen():
        try:
            ctx = build_analysis(q, target_year=year, with_text=text, client=_client)
        except Exception as e:
            yield _sse({"node": "__error__", "status": "error", "msg": str(e)})
            return
        # 1) emit the summary (score, features) so the UI can paint gauges immediately
        yield _sse({"node": "__summary__", "status": "done", "payload": ctx.summary()})
        # 2) stream the agent graph
        for ev in stream_agent_graph(ctx.agent_ctx(), ctx.score.to_dict()):
            yield _sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/portfolio")
def portfolio(tickers: str, year: Optional[int] = None):
    out = []
    for tk in [t.strip() for t in tickers.split(",") if t.strip()][:25]:
        try:
            ctx = build_analysis(tk, target_year=year, with_text=False, client=_client)
            s = ctx.score
            out.append({"ticker": tk.upper(), "name": ctx.panel.entity,
                        "fiscal_year": ctx.forensic.fiscal_year,
                        "score": round(s.calibrated_p, 4), "band": s.band,
                        "confidence": round(s.confidence, 3),
                        "top_signal": _top_signal(s)})
        except Exception as e:
            out.append({"ticker": tk.upper(), "error": str(e)})
    ranked = sorted([o for o in out if "score" in o], key=lambda o: -o["score"])
    errors = [o for o in out if "error" in o]
    return {"ranked": ranked, "errors": errors}


def _top_signal(score) -> str:
    cand = [s for s in score.signals if s.evidence is not None]
    if not cand:
        return ""
    top = max(cand, key=lambda s: s.evidence)
    return top.name


def _json_safe(obj):
    """Recursively replace non-finite floats (NaN/Inf) with None so the payload is valid
    JSON (browsers' JSON.parse rejects the bare `NaN`/`Infinity` tokens Python would emit)."""
    import math
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(_json_safe(obj), default=str)}\n\n"


@app.get("/api/eval")
def eval_report():
    """Return the Phase-3 backtest/ablation report (data/models/report.json)."""
    from ..config import DATA_DIR
    p = DATA_DIR / "models" / "report.json"
    if not p.exists():
        return JSONResponse({"error": "No eval report. Run scripts/train_models.py."},
                            status_code=404)
    return json.loads(p.read_text())


@app.get("/api/screen")
def screen(k: int = 25, audit: int = 5):
    """Cost-gated universe screen: rank the lake's gold table, return top-k + audit sample."""
    from ..agents.gating import gating_summary, score_universe_cheap, select_candidates
    from ..lake.store import MedallionStore
    gold = MedallionStore().read("gold_firm_filing_features")
    if gold is None or gold.empty:
        return JSONResponse({"error": "No gold table. Run scripts/build_universe.py."},
                            status_code=404)
    # screen the most recent fiscal year per firm (the live triage view)
    latest = gold.sort_values("fiscal_year").groupby("cik", as_index=False).tail(1)
    scored = score_universe_cheap(latest)
    cand = select_candidates(scored, k=k, audit=audit)
    cols = ["ticker", "name", "fiscal_year", "cheap_score", "selection_reason", "rank",
            "beneish_m", "dechow_f", "accruals_to_ta", "cfo_ni_ratio", "label"]
    rows = cand.reindex(columns=cols).to_dict(orient="records")
    return {"summary": gating_summary(scored, cand), "candidates": rows}


@app.get("/api/portfolio_lake")
def portfolio_lake():
    """All latest-year firms ranked by cheap score (for the portfolio/backtest view)."""
    from ..agents.gating import score_universe_cheap
    from ..lake.store import MedallionStore
    gold = MedallionStore().read("gold_firm_filing_features")
    if gold is None or gold.empty:
        return JSONResponse({"error": "No gold table."}, status_code=404)
    latest = gold.sort_values("fiscal_year").groupby("cik", as_index=False).tail(1)
    scored = score_universe_cheap(latest).sort_values("cheap_score", ascending=False)
    cols = ["ticker", "name", "fiscal_year", "cheap_score", "beneish_m", "dechow_f",
            "accruals_to_ta", "cfo_ni_ratio", "label"]
    return {"rows": scored.reindex(columns=cols).head(120).to_dict(orient="records")}


@app.get("/api/alerts")
def alerts(limit: int = 100):
    """Recent autonomous-Sentinel irregularity alerts, highest risk first."""
    from ..monitor import Sentinel
    df = Sentinel(client=_client).alerts(limit=limit)
    if df is None or df.empty:
        return {"alerts": [], "count": 0}
    rows = _json_safe(df.to_dict(orient="records"))
    return {"alerts": rows, "count": len(rows)}


@app.get("/api/sentinel/scan")
def sentinel_scan(source: str = "daily", date: Optional[str] = None,
                  limit: int = 20, topk: int = 5):
    """Trigger one Sentinel scan (synchronous). source = daily | watchlist."""
    import datetime as _dt
    from ..monitor import Sentinel
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    try:
        summ = Sentinel(client=_client).scan(on=date, source=source, limit=limit,
                                             topk=topk, stamp=stamp)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return summ.to_dict()


@app.get("/api/sentinel/stream")
def sentinel_stream(source: str = "daily", date: Optional[str] = None, limit: int = 30):
    """SSE: live watchdog sweep — one event per filer the instant it is scored."""
    import datetime as _dt
    from ..monitor import Sentinel
    stamp = _dt.datetime.now().isoformat(timespec="seconds")

    def gen():
        sentinel = Sentinel(client=_client)
        try:
            for ev in sentinel.stream_scan(on=date, source=source, limit=limit, stamp=stamp):
                yield _sse(ev)
        except Exception as e:
            yield _sse({"type": "error", "msg": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/dossier.pdf")
def dossier_pdf(q: str, year: Optional[int] = None):
    """Generate the forensic dossier PDF for a filing — 'exactly what they're doing'."""
    from fastapi.responses import Response
    from ..agents.orchestrator import run_agent_graph
    from ..report import build_dossier_pdf
    try:
        ctx = build_analysis(q, target_year=year, with_text=True, client=_client)
        dossier = run_agent_graph(ctx.agent_ctx(), ctx.score.to_dict())
        pdf = build_dossier_pdf(ctx, dossier)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    fname = f"CASSANDRA_{(ctx.ref.ticker or ctx.ref.cik)}_FY{ctx.forensic.fiscal_year}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/")
def index():
    # Prefer the exported Next.js workstation (full experience incl. watchdog map); fall back
    # to the self-contained built-in UI when the export isn't present (local dev).
    exp = _EXPORT / "index.html"
    if exp.exists():
        return FileResponse(exp)
    idx = WEB_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"error": "UI not built"}, status_code=404)


# ---- static Next.js export (mounted last so explicit routes & /api win) -------------------
from fastapi.staticfiles import StaticFiles  # noqa: E402

if (_EXPORT / "_next").exists():
    app.mount("/_next", StaticFiles(directory=str(_EXPORT / "_next")), name="next-assets")
if _EXPORT.exists():
    # serves favicon and any other top-level export assets; index() above handles "/"
    app.mount("/assets", StaticFiles(directory=str(_EXPORT)), name="export-root")
