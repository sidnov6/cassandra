"""Cost gating (blueprint §6.6).

Running the LLM agent graph on every filing is financially and latency-prohibitive. The
cheap towers score the *entire* universe; the agent graph runs only on the **top-k
candidates** plus a small **random audit sample** (to monitor for missed cases / drift).
This is also how a real desk allocates scarce analyst attention.
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from ..model.train import GRAPH_COLS, TABULAR_COLS


def score_universe_cheap(gold: pd.DataFrame) -> pd.DataFrame:
    """Add a cheap `cheap_score` to every gold row using the trained tabular tower if present,
    else a transparent heuristic from the forensic ratios."""
    g = gold.copy()
    bundle_path = DATA_DIR / "models" / "towers.pkl"
    if bundle_path.exists():
        try:
            with open(bundle_path, "rb") as f:
                bundle = pickle.load(f)
            X = g.reindex(columns=bundle["tabular_cols"]).apply(pd.to_numeric, errors="coerce")
            g["cheap_score"] = bundle["tabular"].predict_proba(X)[:, 1]
            g["cheap_source"] = "trained_tabular_tower"
            return g
        except Exception:
            pass
    # heuristic fallback
    m = pd.to_numeric(g.get("beneish_m"), errors="coerce")
    f = pd.to_numeric(g.get("dechow_f"), errors="coerce")
    acc = pd.to_numeric(g.get("accruals_to_ta"), errors="coerce")
    g["cheap_score"] = (1 / (1 + np.exp(-(m + 1.78))) * 0.5
                        + (f.clip(0, 4) / 4) * 0.3 + acc.clip(0, 0.2) / 0.2 * 0.2).fillna(0)
    g["cheap_source"] = "heuristic"
    return g


def select_candidates(scored: pd.DataFrame, k: int = 20, audit: int = 5,
                      seed: int = 7, score_col: str = "cheap_score") -> pd.DataFrame:
    """Return the gated candidate set: top-k by score + a random audit sample of the rest.

    Adds `selection_reason` (top_k | audit_sample) and `rank`. Deterministic given `seed`.
    """
    s = scored.sort_values(score_col, ascending=False).reset_index(drop=True)
    s["rank"] = np.arange(1, len(s) + 1)
    topk = s.head(k).copy()
    topk["selection_reason"] = "top_k"
    rest = s.iloc[k:]
    if audit > 0 and len(rest) > 0:
        sample = rest.sample(n=min(audit, len(rest)), random_state=seed).copy()
        sample["selection_reason"] = "audit_sample"
        cand = pd.concat([topk, sample], ignore_index=True)
    else:
        cand = topk
    return cand


def gating_summary(scored: pd.DataFrame, candidates: pd.DataFrame) -> dict:
    n = len(scored)
    n_cand = len(candidates)
    return {
        "universe_size": int(n),
        "agent_runs": int(n_cand),
        "cost_reduction": round(1 - n_cand / n, 3) if n else 0.0,
        "top_k": int((candidates["selection_reason"] == "top_k").sum()),
        "audit_sample": int((candidates["selection_reason"] == "audit_sample").sum()),
        "cheap_source": scored["cheap_source"].iloc[0] if "cheap_source" in scored else "n/a",
    }
