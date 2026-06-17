"""Medallion build pipeline (blueprint §5.1).

ingest_company:  EDGAR -> bronze_filings + silver_financials (PIT) + silver_text_sections
                 + silver_graph_edges (auditor)
build_universe:  ingest a basket, align labels, build the firm-auditor graph, then emit
                 gold_firm_filing_features — one point-in-time row per (firm, fiscal year)
                 with forensic + benford + graph features and the commission-aligned label.

This gold table is the modeling input for Phase 3 (towers / fusion / backtest).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from ..features.benford import benford_analysis
from ..features.forensic import compute_forensic
from ..features.graph import (auditor_feature_row, build_firm_auditor_graph,
                              extract_auditor_from_text)
from ..ingest.edgar import EdgarClient
from ..ingest.xbrl import build_panel, numeric_population_for_accession
from ..labels.aligned import build_labels_aligned, label_for_filing
from ..labels.known_cases import CaseLabel, load_cases
from .store import MedallionStore


def _now(client: EdgarClient) -> str:
    # avoid Date.now-style nondeterminism in tooling; use SEC-independent stamp slot
    return ""


def ingest_company(client: EdgarClient, store: MedallionStore, query: str,
                   with_text: bool = True) -> Optional[dict]:
    """Ingest one company into bronze/silver. Returns context for gold building, or None."""
    ref = client.resolve(query)
    if ref is None:
        return None
    try:
        facts = client.company_facts(ref.cik)
    except Exception:
        return None
    panel = build_panel(facts)
    if not panel.years:
        return None

    # ---- bronze_filings ----
    try:
        filings = client.recent_filings(ref.cik, forms=("10-K",), limit=40)
    except Exception:
        filings = []
    if filings:
        bdf = pd.DataFrame([{
            "cik": ref.cik, "ticker": ref.ticker, "accession": f["accession"],
            "form_type": f["form"], "filing_date": f["filing_date"],
            "period_of_report": f["period_of_report"], "primary_doc": f.get("primary_doc"),
            "is_amendment": f["is_amendment"],
        } for f in filings])
        store.append("bronze_filings", bdf, key_cols=["accession"], note=f"ingest {ref.ticker}")

    # ---- silver_financials (long, PIT, as-filed) ----
    rows = []
    for fye in panel.years:
        for concept in panel.df.columns:
            v = panel.get(concept, fye)
            if v is None:
                continue
            prov = panel.provenance.get(concept, {}).get(fye.isoformat(), {})
            rows.append({
                "cik": ref.cik, "accession": prov.get("accn"), "period": fye.isoformat(),
                "point_in_time_date": prov.get("filed"), "concept": concept,
                "taxonomy_tag": prov.get("tag"), "value": float(v),
                "is_amendment": prov.get("is_amendment", False),
            })
    if rows:
        store.append("silver_financials", pd.DataFrame(rows),
                     key_cols=["cik", "period", "concept"], note=f"ingest {ref.ticker}")

    # ---- auditor (graph edge) + optional text sections, from the latest 10-K ----
    auditor = None
    if with_text and filings:
        latest = next((f for f in filings if not f["is_amendment"] and f.get("primary_doc")), None)
        if latest:
            try:
                html = client.filing_text(ref.cik, latest["accession"], latest["primary_doc"])
                from ..features.text import strip_html, extract_sections
                text = strip_html(html)
                auditor = extract_auditor_from_text(text)
                secs = extract_sections(text)
                if secs:
                    sdf = pd.DataFrame([{
                        "cik": ref.cik, "accession": latest["accession"], "section_type": k,
                        "char_start": v[1], "char_end": v[2], "text_len": len(v[0]),
                    } for k, v in secs.items()])
                    store.append("silver_text_sections", sdf,
                                 key_cols=["cik", "accession", "section_type"], note=ref.ticker)
            except Exception:
                pass
    if auditor:
        edf = pd.DataFrame([{
            "src_node": f"firm:{ref.cik}", "dst_node": f"aud:{auditor}",
            "firm_cik": ref.cik, "auditor": auditor, "edge_type": "AUDITED_BY",
            "as_of": panel.latest_fye().isoformat(), "source_accession": None,
        }])
        store.append("silver_graph_edges", edf, key_cols=["src_node", "dst_node"], note=ref.ticker)

    return {"ref": ref, "facts": facts, "panel": panel, "auditor": auditor}


def build_universe(queries: list[str], store: Optional[MedallionStore] = None,
                   with_text: bool = True, progress=None) -> dict:
    """Ingest a basket of companies and emit the gold modeling table. Returns a summary."""
    store = store or MedallionStore()
    client = EdgarClient()

    # 1) resolve labels' CIKs so labels_aligned + label_for_filing work by CIK
    cases = load_cases()
    for c in cases:
        if not c.cik:
            ref = client.resolve(c.ticker or c.name)
            if ref:
                c.cik = ref.cik
    labels_aligned = build_labels_aligned(cases)
    if not labels_aligned.empty:
        store.write("labels_aligned", labels_aligned, note="aligned to commission period")

    # 2) ingest each company
    ctxs = []
    edge_rows = []
    for i, q in enumerate(queries):
        if progress:
            progress(i, len(queries), q)
        ctx = ingest_company(client, store, q, with_text=with_text)
        if ctx:
            ctxs.append(ctx)
            if ctx["auditor"]:
                edge_rows.append({"firm_cik": ctx["ref"].cik, "auditor": ctx["auditor"],
                                  "as_of": ctx["panel"].latest_fye().isoformat()})

    # 3) firm-auditor graph features (needs labels for auditor AAER rate)
    edges_df = pd.DataFrame(edge_rows) if edge_rows else pd.DataFrame(
        columns=["firm_cik", "auditor", "as_of"])
    label_df = pd.DataFrame([{"cik": c.cik, "label": 1} for c in cases if c.cik])
    _, aud_feats = build_firm_auditor_graph(edges_df, label_df)

    # 4) gold: one PIT row per (firm, fiscal year)
    gold_rows = []
    for ctx in ctxs:
        ref, facts, panel, auditor = ctx["ref"], ctx["facts"], ctx["panel"], ctx["auditor"]
        af = auditor_feature_row(auditor, aud_feats)
        for fye in panel.years:
            accn = panel.accession_for(fye)
            bf = benford_analysis(numeric_population_for_accession(facts, accn)) if accn else None
            rep = compute_forensic(panel, bf, target_fye=fye)
            if rep is None:
                continue
            lab = label_for_filing(ref.cik, fye.year, labels_aligned)
            row = {
                "cik": ref.cik, "ticker": ref.ticker, "name": panel.entity,
                "accession": accn, "period": fye.isoformat(), "fiscal_year": fye.year,
                "point_in_time_date": (panel.provenance.get("assets", {})
                                       .get(fye.isoformat(), {}).get("filed")),
                **{k: v for k, v in rep.features.items() if isinstance(v, (int, float))},
                "auditor": auditor, "auditor_risk": af["auditor_risk"],
                "auditor_is_bign": af["auditor_is_bign"],
                "auditor_client_count": af["auditor_client_count"],
                **lab,
            }
            gold_rows.append(row)

    gold = pd.DataFrame(gold_rows)
    if not gold.empty:
        store.write("gold_firm_filing_features", gold, note="modeling table",
                    partition_cols=["fiscal_year"])

    return {
        "companies_ingested": len(ctxs),
        "gold_rows": int(len(gold)),
        "positives": int(gold["label"].sum()) if not gold.empty else 0,
        "auditors": len(aud_feats),
        "tables": store.tables(),
    }
