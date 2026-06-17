"""Sanity tests for the forensic math, point-in-time hygiene, and scoring contracts.

Run: python -m pytest tests/ -q     (or: python tests/test_core.py)
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cassandra.features.benford import benford_analysis
from cassandra.features.forensic import beneish_m, _BENEISH
from cassandra.model.scorer import FusionScorer, _evidence, _logistic


def test_evidence_monotonic_and_bounded():
    # higher value -> higher risk evidence when higher_is_riskier
    lo = _evidence(0.0, threshold=1.0, scale=0.5, higher_is_riskier=True)
    hi = _evidence(2.0, threshold=1.0, scale=0.5, higher_is_riskier=True)
    assert 0.0 <= lo <= hi <= 1.0
    # at threshold -> 0.5
    assert abs(_evidence(1.0, 1.0, 0.5) - 0.5) < 1e-9
    # None passes through
    assert _evidence(None, 1.0, 0.5) is None


def test_beneish_neutral_components_give_baseline():
    # all-neutral components reproduce Beneish's constant + neutral index contributions
    neutral = dict(DSRI=1, GMI=1, AQI=1, SGI=1, DEPI=1, SGAI=1, LVGI=1, TATA=0)
    m = beneish_m(neutral)
    expected = (_BENEISH["c"] + _BENEISH["dsri"] + _BENEISH["gmi"] + _BENEISH["aqi"]
                + _BENEISH["sgi"] + _BENEISH["depi"] + _BENEISH["sgai"] + _BENEISH["lvgi"])
    assert abs(m - expected) < 1e-9


def test_benford_flags_uniform_as_nonconformant():
    # a uniform 1..9 population should deviate from Benford (which is front-loaded)
    vals = [float(d) for d in range(1, 10)] * 30  # 270 values, uniform leading digits
    res = benford_analysis(vals)
    assert res is not None
    assert res.mad > 0.015  # well past Nigrini's nonconformity threshold
    assert 0.0 <= res.anomaly_score <= 1.0


def test_scorer_separates_clean_from_dirty():
    s = FusionScorer()
    clean = {"features": {"beneish_m": -2.6, "dechow_f": 0.4, "accruals_to_ta": 0.0,
                          "cfo_ni_ratio": 1.1, "altman_z": 4.0, "dso_yoy_delta": -1.0,
                          "benford_anomaly": 0.1}}
    dirty = {"features": {"beneish_m": -0.5, "dechow_f": 2.4, "accruals_to_ta": 0.12,
                          "cfo_ni_ratio": -0.2, "altman_z": 3.0, "dso_yoy_delta": 12.0,
                          "benford_anomaly": 0.7}}
    sc_clean = s.score(clean, None, None)
    sc_dirty = s.score(dirty, None, None)
    assert sc_clean.calibrated_p < 0.4 < sc_dirty.calibrated_p
    assert sc_clean.band == "LOW" and sc_dirty.band in ("WATCH", "ELEVATED")
    # probabilities are well-formed
    for sc in (sc_clean, sc_dirty):
        assert 0.0 <= sc.calibrated_p <= 1.0
        assert abs(sum(sc.contributions.values()) - 1.0) < 1e-6


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} sanity tests passed.")
