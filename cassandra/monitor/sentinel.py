"""The Sentinel — an autonomous, continuously-running irregularity detector.

Pipeline per scan (blueprint §6.6 cost gating + §11 alerting):
  1. Pull newly-filed reports (EDGAR daily index, or the tracked watchlist).
  2. Skip anything already alerted on (idempotent — safe to run forever on a schedule).
  3. Cheap-score every candidate (forensic towers; no LLM, no text fetch) and rank.
  4. Gate: the top-k riskiest get the FULL agent dossier; the rest get a lightweight alert
     only if they cross the watch threshold.
  5. Append alerts to the lake (`sentinel_alerts`), deduped on accession.

Designed to run on a schedule (cron / systemd / the bundled daemon). Each run is bounded by
`limit`; at corpus scale you fan out across dates/sectors and raise the cap.
"""
from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from ..agents.orchestrator import run_agent_graph
from ..ingest.crawler import crawl_daily_index
from ..ingest.edgar import EdgarClient
from ..lake.store import MedallionStore
from ..pipeline import build_analysis
from .geo import locate


@dataclasses.dataclass
class ScanSummary:
    index_date: str
    source: str
    candidates: int
    scored: int
    flagged: int
    agent_reviewed: int
    new_alerts: int
    elevated: int

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


class Sentinel:
    def __init__(self, store: Optional[MedallionStore] = None, client: Optional[EdgarClient] = None):
        self.store = store or MedallionStore()
        self.client = client or EdgarClient()

    # ---------------------------------------------------------------- alert store
    def _processed(self) -> set[str]:
        df = self.store.read("sentinel_alerts")
        return set(df["accession"].astype(str)) if df is not None and not df.empty else set()

    def alerts(self, limit: int = 100) -> pd.DataFrame:
        df = self.store.read("sentinel_alerts")
        if df is None or df.empty:
            return pd.DataFrame()
        return df.sort_values(["score"], ascending=False).head(limit)

    def _geo(self, cik: str) -> dict:
        """Business HQ state/city + map coordinates for a filer (from EDGAR submissions)."""
        try:
            subs = self.client.submissions(cik)
            addr = (subs.get("addresses") or {}).get("business") or {}
            state, city = addr.get("stateOrCountry"), addr.get("city")
        except Exception:
            state = city = None
        loc = locate(state, cik) or {}
        return {"state": state or "", "city": (city or "").title(),
                "lat": loc.get("lat"), "lng": loc.get("lng"), "onshore": loc.get("onshore", False)}

    def _alert_record(self, ctx, row, top_flags, run_agents, idx_date, stamp) -> dict:
        g = self._geo(ctx.ref.cik)
        return {
            "accession": ctx.accession or str(row.get("accession", "")),
            "cik": ctx.ref.cik, "ticker": ctx.ref.ticker, "company": ctx.panel.entity,
            "form": str(row.get("form_type", "")), "filing_date": str(row.get("filing_date", "")),
            "fiscal_year": ctx.forensic.fiscal_year,
            "score": round(ctx.score.calibrated_p, 4), "band": ctx.score.band,
            "beneish_m": ctx.forensic.features.get("beneish_m"),
            "cfo_ni_ratio": ctx.forensic.features.get("cfo_ni_ratio"),
            "top_flags": "; ".join(top_flags), "agent_reviewed": run_agents,
            "state": g["state"], "city": g["city"], "lat": g["lat"], "lng": g["lng"],
            "index_date": idx_date, "detected_at": stamp,
        }

    # ---------------------------------------------------------------- candidate sourcing
    def _latest_index_date(self, start: Optional[date] = None, lookback: int = 6) -> Optional[date]:
        d = start or date.today()
        for _ in range(lookback):
            if d.weekday() < 5:  # business day
                idx = crawl_daily_index(d, self.client)
                if not idx.empty:
                    return d
            d -= timedelta(days=1)
        return None

    def _candidates_from_index(self, d: date, forms, limit: int) -> pd.DataFrame:
        idx = crawl_daily_index(d, self.client, forms=forms)
        if idx.empty:
            return idx
        idx = idx[~idx["accession"].astype(str).isin(self._processed())]
        return idx.drop_duplicates("cik").head(limit)

    def _candidates_from_watchlist(self, limit: int) -> pd.DataFrame:
        gold = self.store.read("gold_firm_filing_features")
        if gold is None or gold.empty:
            return pd.DataFrame()
        latest = gold.sort_values("fiscal_year").groupby("cik", as_index=False).tail(1)
        return pd.DataFrame({"cik": latest["cik"], "company": latest["name"],
                             "form_type": "10-K", "filing_date": "",
                             "accession": latest["accession"]}).head(limit)

    # ---------------------------------------------------------------- the scan
    def scan(self, on: Optional[str] = None, source: str = "daily",
             forms: tuple[str, ...] = ("10-K", "10-Q"), limit: int = 40,
             topk: int = 8, watch_threshold: float = 0.40,
             stamp: str = "") -> ScanSummary:
        if source == "watchlist":
            cands = self._candidates_from_watchlist(limit)
            idx_date = "watchlist"
        else:
            d = date.fromisoformat(on) if on else self._latest_index_date()
            if d is None:
                return ScanSummary("none", source, 0, 0, 0, 0, 0, 0)
            cands = self._candidates_from_index(d, forms, limit)
            idx_date = d.isoformat()

        # cheap-score every candidate (no LLM / no text — fast)
        scored = []
        for _, row in cands.iterrows():
            try:
                ctx = build_analysis(str(row["cik"]), with_text=False, client=self.client)
                scored.append((ctx.score.calibrated_p, ctx, row))
            except Exception:
                continue
        scored.sort(key=lambda t: -t[0])

        alerts = []
        agent_reviewed = elevated = 0
        for rank, (p, ctx, row) in enumerate(scored):
            run_agents = rank < topk
            if p < watch_threshold and not run_agents:
                continue  # below the watch line and not in the priority slice
            top_flags: list[str] = []
            if run_agents:
                doss = run_agent_graph(ctx.agent_ctx(), ctx.score.to_dict())
                top_flags = [f["title"] for f in doss["flags"]][:3]
                agent_reviewed += 1
            if ctx.score.band == "ELEVATED":
                elevated += 1
            alerts.append(self._alert_record(ctx, row, top_flags, run_agents, idx_date, stamp))

        new_alerts = 0
        if alerts:
            self.store.append("sentinel_alerts", pd.DataFrame(alerts),
                              key_cols=["accession"], note=f"scan {idx_date}", written_at=stamp)
            new_alerts = len(alerts)

        return ScanSummary(index_date=idx_date, source=source, candidates=int(len(cands)),
                           scored=len(scored), flagged=len(alerts), agent_reviewed=agent_reviewed,
                           new_alerts=new_alerts, elevated=elevated)

    # ---------------------------------------------------------------- live streaming scan
    def stream_scan(self, on: Optional[str] = None, source: str = "daily",
                    forms: tuple[str, ...] = ("10-K", "10-Q"), limit: int = 30,
                    max_agent: int = 10, watch_threshold: float = 0.40, stamp: str = "",
                    pace: float = 0.32):
        """Generator of map events as the drone sweeps: one `scan` event per filer the moment
        it is scored (so the UI flies the drone there in real time), with agent flags inlined
        for detections. Writes alerts at the end. Yields dicts; the API frames them as SSE."""
        if source == "watchlist":
            cands = self._candidates_from_watchlist(limit)
            idx_date = "watchlist"
        else:
            d = date.fromisoformat(on) if on else self._latest_index_date()
            if d is None:
                yield {"type": "done", "scored": 0, "flagged": 0, "agent_reviewed": 0,
                       "elevated": 0, "index_date": "none"}
                return
            cands = self._candidates_from_index(d, forms, limit)
            idx_date = d.isoformat()

        yield {"type": "init", "candidates": int(len(cands)), "index_date": idx_date, "source": source}

        alerts, agent_runs, scored, elevated = [], 0, 0, 0
        for _, row in cands.iterrows():
            try:
                ctx = build_analysis(str(row["cik"]), with_text=False, client=self.client)
            except Exception:
                continue
            scored += 1
            g = self._geo(ctx.ref.cik)
            p = ctx.score.calibrated_p
            flagged = p >= watch_threshold
            top_flags: list[str] = []
            if flagged and agent_runs < max_agent:
                doss = run_agent_graph(ctx.agent_ctx(), ctx.score.to_dict())
                top_flags = [f["title"] for f in doss["flags"]][:3]
                agent_runs += 1
            if ctx.score.band == "ELEVATED":
                elevated += 1
            ev = {
                "type": "scan", "cik": ctx.ref.cik, "ticker": ctx.ref.ticker,
                "company": ctx.panel.entity, "fiscal_year": ctx.forensic.fiscal_year,
                "score": round(p, 4), "band": ctx.score.band, "flagged": flagged,
                "agent_reviewed": flagged and bool(top_flags),
                "top_flags": "; ".join(top_flags),
                "beneish_m": ctx.forensic.features.get("beneish_m"),
                "cfo_ni_ratio": ctx.forensic.features.get("cfo_ni_ratio"),
                "state": g["state"], "city": g["city"], "lat": g["lat"], "lng": g["lng"],
            }
            yield ev
            if flagged:
                alerts.append(self._alert_record(ctx, row, top_flags,
                                                 ev["agent_reviewed"], idx_date, stamp))
            # Cinematic pacing: let the drone visibly fly between targets and linger on a
            # detection long enough for its target-lock to read. (No effect on correctness.)
            if pace:
                import time
                time.sleep(pace + (0.35 if flagged else 0.0))

        if alerts:
            self.store.append("sentinel_alerts", pd.DataFrame(alerts),
                              key_cols=["accession"], note=f"stream {idx_date}", written_at=stamp)
        yield {"type": "done", "scored": scored, "flagged": len(alerts),
               "agent_reviewed": agent_runs, "elevated": elevated, "index_date": idx_date}
