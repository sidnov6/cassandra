"""Layer 3 — Core model: late-fusion scorer + calibration + backtest harness."""
from .scorer import FusionScorer, ModelScore
from .backtest import evaluate_ranking, BacktestResult

__all__ = ["FusionScorer", "ModelScore", "evaluate_ranking", "BacktestResult"]
