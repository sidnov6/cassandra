"""Graph features (blueprint §5.2).

Fraud clusters — same auditor, same partner, contagion through interlocks — which a
pure-tabular model cannot see. The thin slice builds the firm <-> auditor bipartite graph
(the most reliably extractable relation from 10-Ks) and computes classical graph features:

  * auditor_risk        — the auditor's historical AAER/fraud rate across the known universe
  * auditor_client_count — how many tracked filers the auditor signs (degree centrality)
  * auditor_is_bign      — Big-4 indicator

GNN embeddings (GraphSAGE/GAT) and board-interlock / related-party edges are the documented
production upgrade; the classical features are the honest first pass §5.2 calls for.
"""
from __future__ import annotations

import re
from typing import Optional

import networkx as nx
import pandas as pd

BIG_N = {
    "ERNST & YOUNG": "Ernst & Young LLP", "DELOITTE": "Deloitte & Touche LLP",
    "PRICEWATERHOUSECOOPERS": "PricewaterhouseCoopers LLP", "KPMG": "KPMG LLP",
    "BDO": "BDO USA LLP", "GRANT THORNTON": "Grant Thornton LLP",
    "RSM": "RSM US LLP", "MARCUM": "Marcum LLP", "CROWE": "Crowe LLP",
    "MOSS ADAMS": "Moss Adams LLP", "BAKER TILLY": "Baker Tilly US LLP",
}
BIG4 = {"Ernst & Young LLP", "Deloitte & Touche LLP", "PricewaterhouseCoopers LLP", "KPMG LLP"}

_AUD_NAME_RE = re.compile(r"Auditor\s*Name[:\s]+([A-Z][A-Za-z&,\.\s']{3,60}?LLP|[A-Z][A-Za-z&,\.\s']{3,60}?LLC)")
_SIG_RE = re.compile(r"/s/\s*([A-Z][A-Za-z&,\.\s']{3,55}?(?:LLP|LLC|L\.L\.P\.))")


def extract_auditor_from_text(text: Optional[str]) -> Optional[str]:
    """Best-effort auditor name from the 10-K (cover 'Auditor Name:' block, signature, or
    a known-firm mention). Returns a normalized firm name."""
    if not text:
        return None
    head = text[:400_000]
    m = _AUD_NAME_RE.search(head)
    if m:
        return _normalize(m.group(1))
    # known-firm mentions near the audit report
    up = head.upper()
    for key, full in BIG_N.items():
        if key in up:
            return full
    m = _SIG_RE.search(head)
    if m:
        return _normalize(m.group(1))
    return None


def _normalize(name: str) -> str:
    n = re.sub(r"\s+", " ", name).strip().strip(",.")
    up = n.upper()
    for key, full in BIG_N.items():
        if key in up:
            return full
    return n


def build_firm_auditor_graph(edges: pd.DataFrame, labels: Optional[pd.DataFrame] = None
                             ) -> tuple[nx.Graph, dict[str, dict]]:
    """edges: firm_cik, auditor, as_of. labels (optional): cik, label(0/1).
    Returns (graph, per-auditor feature dict)."""
    g = nx.Graph()
    fraud_cik = set()
    if labels is not None and not labels.empty:
        fraud_cik = set(labels.loc[labels["label"] == 1, "cik"].astype(str))

    for _, r in edges.iterrows():
        firm = f"firm:{r['firm_cik']}"
        aud = f"aud:{r['auditor']}"
        g.add_node(firm, kind="firm", cik=str(r["firm_cik"]))
        g.add_node(aud, kind="auditor", name=r["auditor"])
        g.add_edge(firm, aud, edge_type="AUDITED_BY", as_of=r.get("as_of"))

    aud_feats: dict[str, dict] = {}
    for node, data in g.nodes(data=True):
        if data.get("kind") != "auditor":
            continue
        clients = [n for n in g.neighbors(node)]
        ciks = [g.nodes[c].get("cik") for c in clients]
        n_clients = len(clients)
        n_fraud = sum(1 for c in ciks if c in fraud_cik)
        aud_feats[data["name"]] = {
            "auditor_client_count": n_clients,
            "auditor_fraud_clients": n_fraud,
            "auditor_aaer_rate": (n_fraud / n_clients) if n_clients else 0.0,
            "auditor_is_bign": 1 if data["name"] in BIG4 else 0,
        }
    return g, aud_feats


def auditor_feature_row(auditor: Optional[str], aud_feats: dict[str, dict]) -> dict:
    """Graph-feature row for a single filing given its auditor."""
    base = {"auditor": auditor, "auditor_client_count": 0, "auditor_aaer_rate": 0.0,
            "auditor_is_bign": 0, "auditor_risk": 0.0}
    if auditor and auditor in aud_feats:
        f = aud_feats[auditor]
        base.update({
            "auditor_client_count": f["auditor_client_count"],
            "auditor_aaer_rate": f["auditor_aaer_rate"],
            "auditor_is_bign": f["auditor_is_bign"],
            # auditor_risk: AAER rate, with a mild prior pulling small-sample auditors to base
            "auditor_risk": round(f["auditor_aaer_rate"] * (f["auditor_client_count"] /
                                  (f["auditor_client_count"] + 5)), 4),
        })
    return base
