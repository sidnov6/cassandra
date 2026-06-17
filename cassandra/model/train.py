"""Phase-3 training & evaluation engine (blueprint §5.3, §7).

Trains four modality towers, fuses them with an out-of-fold meta-learner, calibrates, and
evaluates under TWO time-respecting protocols:
  * group-aware cross-validation (GroupKFold by firm) — no firm in train & test;
  * expanding-window walk-forward by fiscal year — train on years < T, test on year T
    (strictly-past training; the current year is never in its own training set).
Produces the §7.4 ablation table vs the Beneish, Dechow-F, and class-weighted-GBM baselines,
and persists models + a metrics report consumed by the eval UI.

Honest scope: the seed label set is small (tens of positive firm-years), so absolute metrics
are illustrative with wide intervals; the deliverable is the *rigor of the protocol* and the
relative lift of fusion over baselines, exactly as §7 specifies.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from .backtest import evaluate_ranking

MODEL_DIR = DATA_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

TABULAR_COLS = [
    "beneish_m", "beneish_dsri", "beneish_gmi", "beneish_aqi", "beneish_sgi", "beneish_depi",
    "beneish_sgai", "beneish_lvgi", "beneish_tata", "dechow_f", "rsst_accruals",
    "accruals_to_ta", "cfo_ni_ratio", "altman_z", "altman_x1", "altman_x2", "altman_x3",
    "altman_x4", "altman_x5", "dso", "dsi", "dso_yoy_delta", "dsi_yoy_delta",
    "benford_mad", "benford_anomaly",
]
# NOTE: `auditor_risk`/`auditor_aaer_rate` are intentionally EXCLUDED — they are derived from
# the label set (auditor's fraud-client rate) and would leak the answer into a model feature.
# Only label-free graph features are used here. (auditor_risk is recomputed leave-one-out for
# display only.) See cassandra/features/graph.py.
GRAPH_COLS = ["auditor_is_bign", "auditor_client_count"]


def _fit_gbm(X: pd.DataFrame, y: np.ndarray):
    """Class-weighted gradient boosting (the honest tabular SOTA; RUSBoost spirit)."""
    import lightgbm as lgb
    pos = max(1, int(y.sum()))
    neg = max(1, len(y) - pos)
    clf = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.03, num_leaves=16, max_depth=4,
        min_child_samples=8, subsample=0.8, colsample_bytree=0.8,
        scale_pos_weight=neg / pos, reg_lambda=1.0, random_state=0, verbose=-1)
    clf.fit(X, y)
    return clf


def _fit_logit(X: np.ndarray, y: np.ndarray):
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(max_iter=1000, class_weight="balanced", C=0.5)
    clf.fit(X, y)
    return clf


def _temporal_features(gold: pd.DataFrame) -> pd.DataFrame:
    """Per-firm sequence features: lagged levels, deltas, and 3-yr slopes (escalation).

    Returns a DataFrame aligned 1:1 to `gold.index` (no merge — avoids row blow-up when a
    firm has two fiscal-year-ends in one calendar year, e.g. a fiscal-year-end change)."""
    cols = ["beneish_m", "accruals_to_ta", "dso", "dechow_f", "cfo_ni_ratio"]
    feat_by_idx: dict = {}
    for _, g in gold.groupby("cik"):
        g = g.sort_values("fiscal_year")
        idxs = list(g.index)
        vals = {c: pd.to_numeric(g[c], errors="coerce").values for c in cols}
        for pos in range(len(g)):
            row = {}
            for c in cols:
                cur = vals[c][pos]
                row[f"{c}_lvl"] = cur
                prev = vals[c][pos - 1] if pos >= 1 else np.nan
                row[f"{c}_d1"] = (cur - prev) if (pos >= 1 and pd.notna(prev) and pd.notna(cur)) else np.nan
                window = vals[c][max(0, pos - 3): pos + 1]
                window = window[~np.isnan(window)]
                if len(window) >= 3:
                    x = np.arange(len(window))
                    den = ((x - x.mean()) ** 2).sum()
                    row[f"{c}_slope"] = (((x - x.mean()) * (window - window.mean())).sum() / den) if den else np.nan
                else:
                    row[f"{c}_slope"] = np.nan
            feat_by_idx[idxs[pos]] = row
    return pd.DataFrame.from_dict(feat_by_idx, orient="index").reindex(gold.index)


def _oof_predict(X, y, groups, fit_fn, predict_fn) -> np.ndarray:
    from sklearn.model_selection import GroupKFold
    oof = np.full(len(y), np.nan)
    n_groups = len(np.unique(groups))
    n_splits = min(5, max(2, n_groups))
    gkf = GroupKFold(n_splits=n_splits)
    for tr, te in gkf.split(X, y, groups):
        ytr = y[tr]
        if ytr.sum() == 0 or ytr.sum() == len(ytr):
            oof[te] = float(y.mean())
            continue
        m = fit_fn(X.iloc[tr] if hasattr(X, "iloc") else X[tr], ytr)
        oof[te] = predict_fn(m, X.iloc[te] if hasattr(X, "iloc") else X[te])
    # fill any remaining
    oof[np.isnan(oof)] = float(y.mean())
    return oof


def _gbm_proba(m, X):
    return m.predict_proba(X)[:, 1]


def train_and_evaluate(gold: Optional[pd.DataFrame] = None,
                       text_df: Optional[pd.DataFrame] = None) -> dict:
    if gold is None:
        from ..lake.store import MedallionStore
        gold = MedallionStore().read("gold_firm_filing_features")
    if gold is None or gold.empty:
        raise ValueError("No gold table; run scripts/build_universe.py first.")

    gold = gold.copy()
    gold["label"] = gold["label"].astype(int)
    y = gold["label"].values
    groups = gold["cik"].astype(str).values

    # ---- tower datasets ----
    Xtab = gold.reindex(columns=TABULAR_COLS).apply(pd.to_numeric, errors="coerce")
    Xgr = gold.reindex(columns=GRAPH_COLS).apply(pd.to_numeric, errors="coerce")
    temp = _temporal_features(gold)            # index-aligned to gold
    tempcols = list(temp.columns)
    Xtemp = temp.apply(pd.to_numeric, errors="coerce")

    # ---- OOF tower predictions (group-aware) ----
    oof = {}
    oof["tabular"] = _oof_predict(Xtab, y, groups, _fit_gbm, _gbm_proba)
    oof["graph"] = _oof_predict(Xgr, y, groups, _fit_gbm, _gbm_proba)
    oof["temporal"] = _oof_predict(Xtemp, y, groups, _fit_gbm, _gbm_proba)

    # text tower (optional; company-level, joined on cik)
    have_text = text_df is not None and not text_df.empty
    if have_text:
        from sklearn.preprocessing import StandardScaler
        tmerge = gold.merge(text_df, on="cik", how="left")
        txt_cols = [c for c in text_df.columns if c != "cik"]
        Xtxt_raw = tmerge.reindex(columns=txt_cols).apply(pd.to_numeric, errors="coerce").fillna(0.0).values
        Xtxt = StandardScaler().fit_transform(Xtxt_raw)
        oof["text"] = _oof_predict(Xtxt, y, groups, _fit_logit, lambda m, X: m.predict_proba(X)[:, 1])

    # ---- meta-learner (late fusion) on OOF tower preds ----
    tower_names = list(oof.keys())
    Z = np.column_stack([oof[t] for t in tower_names])
    meta_oof = _oof_predict(pd.DataFrame(Z, columns=tower_names), y, groups,
                            _fit_logit, lambda m, X: m.predict_proba(X)[:, 1])

    # ---- calibration (isotonic on OOF fused) ----
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(out_of_bounds="clip")
    cal = iso.fit_transform(meta_oof, y)

    # ---- metrics ----
    def m(scores):
        return evaluate_ranking(list(scores), list(y), ks=(10, 25, 50)).to_dict()

    fused_metrics = m(cal)

    # ---- ablation table (§7.4) ----
    beneish_score = pd.to_numeric(gold.get("beneish_m"), errors="coerce").fillna(-99).values
    fscore = pd.to_numeric(gold.get("dechow_f"), errors="coerce").fillna(0).values
    ablation = {
        "Beneish M (threshold)": m(beneish_score),
        "Dechow F-Score": m(fscore),
        "GBM tabular-only (RUSBoost spirit)": m(oof["tabular"]),
        "tabular + temporal": m((oof["tabular"] + oof["temporal"]) / 2),
        "tabular + temporal + graph": m((oof["tabular"] + oof["temporal"] + oof["graph"]) / 3),
        "FULL fusion (+text)" if have_text else "FULL fusion": fused_metrics,
    }

    # ---- walk-forward (expanding window by fiscal year) ----
    wf = _walk_forward(gold, Xtab, y)

    # ---- fit final full-data models for serving ----
    final = {
        "tabular": _fit_gbm(Xtab, y), "graph": _fit_gbm(Xgr, y), "temporal": _fit_gbm(Xtemp, y),
        "meta": _fit_logit(Z, y), "iso": iso,
        "tower_names": tower_names, "tabular_cols": TABULAR_COLS, "graph_cols": GRAPH_COLS,
        "temporal_cols": tempcols,
    }
    with open(MODEL_DIR / "towers.pkl", "wb") as fpk:
        pickle.dump(final, fpk)

    report = {
        "n_rows": int(len(gold)), "n_firms": int(gold["cik"].nunique()),
        "positives": int(y.sum()), "base_rate": float(y.mean()),
        "towers": tower_names,
        "fused": fused_metrics,
        "ablation": ablation,
        "walk_forward": wf,
        "tower_oof_pr_auc": {t: evaluate_ranking(list(oof[t]), list(y)).pr_auc for t in tower_names},
    }
    (MODEL_DIR / "report.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def _walk_forward(gold: pd.DataFrame, Xtab: pd.DataFrame, y: np.ndarray) -> list[dict]:
    """Expanding-window: train on years < T, test on year T (strictly-past). Per-fold PR-AUC."""
    years = sorted(gold["fiscal_year"].dropna().unique())
    out = []
    yr = gold["fiscal_year"].values
    for i in range(3, len(years)):
        T = years[i]
        tr = yr < T
        te = yr == T
        if te.sum() < 3 or y[tr].sum() == 0 or y[te].sum() == 0:
            continue
        try:
            mdl = _fit_gbm(Xtab[tr], y[tr])
            p = mdl.predict_proba(Xtab[te])[:, 1]
            res = evaluate_ranking(list(p), list(y[te]), ks=(10, 25))
            out.append({"test_year": int(T), "n_test": int(te.sum()),
                        "positives": int(y[te].sum()), "pr_auc": round(res.pr_auc, 4),
                        "p_at_10": round(res.precision_at_k.get(10, 0), 4)})
        except Exception:
            continue
    return out
