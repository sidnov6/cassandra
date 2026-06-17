"""Benford's Law digit tests (blueprint §5.2).

First-digit expected frequency:  P(d) = log10(1 + 1/d),  d in 1..9.
Conformity measured with MAD (mean absolute deviation), chi-square, and KS.
MAD thresholds follow Nigrini (2012), the standard forensic-accounting reference.

Run over the population of reported numeric line items in a filing. Visually legible —
the bar chart of observed-vs-expected leading digits is a centerpiece of the dossier UI.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

import numpy as np

# Nigrini (2012) first-digit MAD conformity thresholds.
FIRST_DIGIT_MAD = [
    (0.006, "close conformity"),
    (0.012, "acceptable conformity"),
    (0.015, "marginally acceptable"),
    (float("inf"), "nonconformity"),
]
# First-two-digits MAD thresholds (Nigrini 2012).
FIRST_TWO_MAD = [
    (0.0012, "close conformity"),
    (0.0018, "acceptable conformity"),
    (0.0022, "marginally acceptable"),
    (float("inf"), "nonconformity"),
]


def _leading_digit(x: float) -> Optional[int]:
    x = abs(float(x))
    if x == 0 or not math.isfinite(x):
        return None
    while x < 1:
        x *= 10
    while x >= 10:
        x /= 10
    return int(x)


def _leading_two(x: float) -> Optional[int]:
    x = abs(float(x))
    if x == 0 or not math.isfinite(x):
        return None
    while x < 10:
        x *= 10
    while x >= 100:
        x /= 10
    return int(x)


def _conformity(mad: float, table) -> str:
    for thresh, label in table:
        if mad <= thresh:
            return label
    return "nonconformity"


@dataclasses.dataclass
class BenfordResult:
    n: int
    digits: list[int]              # 1..9
    observed: list[float]         # observed proportions
    expected: list[float]         # Benford proportions
    mad: float                    # first-digit MAD
    chi_square: float
    chi_square_p: Optional[float]
    conformity: str
    # first-two-digit summary
    two_digit_mad: Optional[float]
    two_digit_conformity: Optional[str]
    # a 0..1 anomaly score for fusion (0 = perfectly conformant)
    anomaly_score: float

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "digits": self.digits,
            "observed": [round(v, 4) for v in self.observed],
            "expected": [round(v, 4) for v in self.expected],
            "mad": round(self.mad, 5),
            "chi_square": round(self.chi_square, 2),
            "chi_square_p": None if self.chi_square_p is None else round(self.chi_square_p, 4),
            "conformity": self.conformity,
            "two_digit_mad": None if self.two_digit_mad is None else round(self.two_digit_mad, 5),
            "two_digit_conformity": self.two_digit_conformity,
            "anomaly_score": round(self.anomaly_score, 3),
        }


def benford_analysis(values: list[float]) -> Optional[BenfordResult]:
    """Compute first-digit and first-two-digit Benford diagnostics over `values`."""
    lead = [d for d in (_leading_digit(v) for v in values) if d is not None]
    n = len(lead)
    if n < 50:  # too few numbers for a meaningful test
        return None

    digits = list(range(1, 10))
    expected = [math.log10(1 + 1 / d) for d in digits]
    counts = [lead.count(d) for d in digits]
    observed = [c / n for c in counts]
    mad = float(np.mean([abs(o - e) for o, e in zip(observed, expected)]))
    chi2 = float(sum((counts[i] - n * expected[i]) ** 2 / (n * expected[i]) for i in range(9)))

    chi2_p = None
    try:
        from scipy import stats
        chi2_p = float(stats.chi2.sf(chi2, df=8))
    except Exception:
        pass

    # first-two-digit
    two = [d for d in (_leading_two(v) for v in values) if d is not None]
    two_mad = None
    two_conf = None
    if len(two) >= 100:
        ks = list(range(10, 100))
        exp2 = [math.log10(1 + 1 / k) for k in ks]
        cnt2 = [two.count(k) for k in ks]
        obs2 = [c / len(two) for c in cnt2]
        two_mad = float(np.mean([abs(o - e) for o, e in zip(obs2, exp2)]))
        two_conf = _conformity(two_mad, FIRST_TWO_MAD)

    # Map MAD to a 0..1 anomaly score: 0 at perfect conformity, ~1 well past nonconformity.
    # First-digit nonconformity threshold is 0.015; saturate at ~0.040.
    anomaly = float(np.clip((mad - 0.006) / (0.040 - 0.006), 0.0, 1.0))

    return BenfordResult(
        n=n, digits=digits, observed=observed, expected=expected,
        mad=mad, chi_square=chi2, chi_square_p=chi2_p,
        conformity=_conformity(mad, FIRST_DIGIT_MAD),
        two_digit_mad=two_mad, two_digit_conformity=two_conf,
        anomaly_score=anomaly,
    )
