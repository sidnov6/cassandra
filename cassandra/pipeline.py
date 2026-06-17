"""End-to-end analysis pipeline: resolve -> ingest (PIT) -> features -> fuse -> agents.

Produces an `AnalysisContext` consumed by both the CLI (run agents to completion) and the
API (stream agent events). Every stage degrades gracefully: no text -> text tower skipped;
no LLM key -> deterministic agents; missing concepts -> partial features, never a crash.
"""
from __future__ import annotations

import dataclasses
import math
from datetime import date
from typing import Optional

from .features.benford import benford_analysis
from .features.forensic import ForensicReport, compute_forensic
from .features.text import TextReport, analyze_text
from .ingest.edgar import CompanyRef, EdgarClient
from .ingest.xbrl import build_panel, numeric_population_for_accession, FinancialsPanel
from .model.scorer import FusionScorer, ModelScore


@dataclasses.dataclass
class AnalysisContext:
    ref: CompanyRef
    panel: FinancialsPanel
    forensic: ForensicReport
    text: Optional[TextReport]
    score: ModelScore
    target_fye: date
    accession: Optional[str]

    def agent_ctx(self) -> dict:
        return {
            "cik": self.ref.cik, "entity": self.panel.entity,
            "accession": self.accession,
            "fiscal_year": self.forensic.fiscal_year,
            "point_in_time": self.target_fye.isoformat(),
            "features": self.forensic.features,
            "interpretations": self.forensic.interpretations,
            "benford": self.forensic.benford.to_dict() if self.forensic.benford else None,
            "text": self.text.to_dict() if self.text else None,
        }

    def summary(self) -> dict:
        return {
            "company": {"cik": self.ref.cik, "ticker": self.ref.ticker,
                        "name": self.panel.entity},
            "filing": {"accession": self.accession,
                       "fiscal_year": self.forensic.fiscal_year,
                       "point_in_time": self.target_fye.isoformat(),
                       "fiscal_years_available": self.panel.fiscal_years},
            "score": self.score.to_dict(),
            "forensic": self.forensic.to_dict(),
            "text": self.text.to_dict() if self.text else None,
        }


def _fundamentals_perf(forensic: ForensicReport) -> Optional[float]:
    """Signed [-1,1] fundamentals signal: blends revenue growth and cash-quality health."""
    f = forensic.features
    sgi = f.get("beneish_sgi")
    cfo_ni = f.get("cfo_ni_ratio")
    parts = []
    if isinstance(sgi, (int, float)) and math.isfinite(sgi):
        parts.append(math.tanh((sgi - 1.05) * 2.5))   # growth above ~5% reads positive
    if isinstance(cfo_ni, (int, float)) and math.isfinite(cfo_ni):
        parts.append(math.tanh((cfo_ni - 1.0) * 1.5))  # cash-backed earnings read positive
    if not parts:
        return None
    return max(-1.0, min(1.0, sum(parts) / len(parts)))


def _find_filing_for(client: EdgarClient, ref: CompanyRef, fye: date) -> Optional[dict]:
    """Locate the original 10-K whose period_of_report matches the fiscal-year-end."""
    try:
        filings = client.recent_filings(ref.cik, forms=("10-K",), limit=40)
    except Exception:
        return None
    target = fye.isoformat()
    for fil in filings:
        if fil.get("is_amendment"):
            continue
        if fil.get("period_of_report") == target:
            return fil
    return None


def build_analysis(query: str, target_year: Optional[int] = None,
                   with_text: bool = True, client: Optional[EdgarClient] = None) -> AnalysisContext:
    client = client or EdgarClient()
    ref = client.resolve(query)
    if ref is None:
        raise ValueError(f"Could not resolve company: {query!r}")

    facts = client.company_facts(ref.cik)
    panel = build_panel(facts)
    if not panel.years:
        raise ValueError(f"No XBRL financial history for {ref.title} (CIK {ref.cik}).")

    if target_year is not None:
        target_fye = next((d for d in panel.years if d.year == target_year), panel.latest_fye())
    else:
        target_fye = panel.latest_fye()

    accn = panel.accession_for(target_fye)
    benford = benford_analysis(numeric_population_for_accession(facts, accn)) if accn else None
    forensic = compute_forensic(panel, benford, target_fye)

    text_report: Optional[TextReport] = None
    if with_text:
        text_report = _fetch_text(client, ref, panel, target_fye, forensic)

    # Point-in-time: the temporal tower must only see filings up to the scored year. The full
    # series is retained for the UI trend chart, but the scorer receives a truncated view so no
    # future filing can leak into the score (blueprint §7 no-look-ahead invariant).
    pit_series = forensic.series.loc[:target_fye]
    score = FusionScorer().score(
        forensic.to_dict(),
        text_report.to_dict() if (text_report and text_report.available) else None,
        pit_series,
    )
    return AnalysisContext(ref=ref, panel=panel, forensic=forensic, text=text_report,
                           score=score, target_fye=target_fye, accession=accn)


def _fetch_text(client, ref, panel, target_fye, forensic) -> Optional[TextReport]:
    try:
        fil = _find_filing_for(client, ref, target_fye)
        if not fil or not fil.get("primary_doc"):
            return TextReport(available=False, sections_found=[],
                              note="Could not locate the 10-K primary document for this year.")
        html = client.filing_text(ref.cik, fil["accession"], fil["primary_doc"])
        prior_html = None
        prior_fye = panel.prior(target_fye)
        if prior_fye:
            pf = _find_filing_for(client, ref, prior_fye)
            if pf and pf.get("primary_doc"):
                try:
                    prior_html = client.filing_text(ref.cik, pf["accession"], pf["primary_doc"])
                except Exception:
                    prior_html = None
        return analyze_text(html, prior_html, _fundamentals_perf(forensic))
    except Exception as e:  # graceful: text tower simply degrades
        return TextReport(available=False, sections_found=[], note=f"Text unavailable: {e}")
