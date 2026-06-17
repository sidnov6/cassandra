"""Point-in-time evaluation metrics (blueprint §2.2, §7.3).

At a <1% base rate, accuracy and ROC-AUC lie. The honest metrics rank a finite analyst
shortlist: PR-AUC, Precision@k, Recall@k, NDCG@k, top-decile lift, and calibration
(Brier / ECE). This module implements them directly so the training loop and the UI
portfolio view share one definition of "good".
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

import numpy as np


@dataclasses.dataclass
class BacktestResult:
    n: int
    positives: int
    base_rate: float
    pr_auc: float
    roc_auc: float
    precision_at_k: dict[int, float]
    recall_at_k: dict[int, float]
    ndcg_at_k: dict[int, float]
    top_decile_lift: float
    brier: float
    ece: float

    def to_dict(self) -> dict:
        return {k: (v if not isinstance(v, dict) else {str(kk): round(vv, 4) for kk, vv in v.items()})
                for k, v in dataclasses.asdict(self).items()}


def _pr_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    try:
        from sklearn.metrics import average_precision_score
        return float(average_precision_score(labels, scores))
    except Exception:
        return float("nan")


def _roc_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    try:
        from sklearn.metrics import roc_auc_score
        return float(roc_auc_score(labels, scores))
    except Exception:
        return float("nan")


def _dcg(rels: list[int]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def evaluate_ranking(scores: list[float], labels: list[int],
                     ks: tuple[int, ...] = (10, 25, 50, 100)) -> BacktestResult:
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    n = len(s)
    pos = int(y.sum())
    base = pos / n if n else 0.0

    order = np.argsort(-s)
    y_ranked = y[order]

    p_at, r_at, ndcg_at = {}, {}, {}
    for k in ks:
        kk = min(k, n)
        topk = y_ranked[:kk]
        p_at[k] = float(topk.sum() / kk) if kk else 0.0
        r_at[k] = float(topk.sum() / pos) if pos else 0.0
        ideal = sorted(y_ranked.tolist(), reverse=True)[:kk]
        idcg = _dcg(ideal)
        ndcg_at[k] = float(_dcg(topk.tolist()) / idcg) if idcg > 0 else 0.0

    decile = max(1, n // 10)
    top_decile_rate = y_ranked[:decile].mean() if decile else 0.0
    lift = float(top_decile_rate / base) if base > 0 else float("nan")

    # calibration
    brier = float(np.mean((s - y) ** 2))
    ece = _expected_calibration_error(s, y)

    return BacktestResult(
        n=n, positives=pos, base_rate=base,
        pr_auc=_pr_auc(s, y), roc_auc=_roc_auc(s, y),
        precision_at_k=p_at, recall_at_k=r_at, ndcg_at_k=ndcg_at,
        top_decile_lift=lift, brier=brier, ece=ece,
    )


def _expected_calibration_error(scores: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    n = len(scores)
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (scores >= lo) & (scores < hi if i < bins - 1 else scores <= hi)
        if not mask.any():
            continue
        conf = scores[mask].mean()
        acc = labels[mask].mean()
        ece += (mask.sum() / n) * abs(conf - acc)
    return float(ece)
