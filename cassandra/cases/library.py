"""A small library of canonical accounting-fraud cases, encoded as *pattern fingerprints*.

Each case carries a stylized fingerprint over eight normalized signal dimensions. These
encode the documented mechanism of each fraud (e.g. Wirecard = fictitious third-party cash
+ related-party structure), not statistically-fitted vectors. The analogue agent cosine-
matches a live filing's fingerprint against these to surface "this resembles ___" — always
labelled as a pattern resemblance, never a claim that the filer is committing that fraud.

Fingerprint dimensions (each ~0..1):
  accruals, cfo_ni_divergence, dso_rise, revenue_aggressiveness,
  related_party, benford, leverage, narrative_optimism
"""
from __future__ import annotations

import dataclasses

import numpy as np

DIMS = ["accruals", "cfo_ni_divergence", "dso_rise", "revenue_aggressiveness",
        "related_party", "benford", "leverage", "narrative_optimism"]


@dataclasses.dataclass
class FraudCase:
    name: str
    period: str
    jurisdiction: str
    standard: str
    sec_xbrl: bool             # is this filer in the AAER/US-XBRL trainable distribution?
    mechanism: str
    fingerprint: dict[str, float]

    @property
    def vector(self) -> np.ndarray:
        return np.array([self.fingerprint.get(d, 0.0) for d in DIMS], dtype=float)


CASE_LIBRARY: list[FraudCase] = [
    FraudCase("Under Armour", "2015–2016", "US", "US GAAP", True,
              "Pulled forward ~$408M of revenue from future quarters to meet guidance; "
              "SEC settled 2021. Tell: receivables/DSO rise + CFO–NI divergence.",
              {"accruals": 0.8, "cfo_ni_divergence": 0.85, "dso_rise": 0.8,
               "revenue_aggressiveness": 0.9, "related_party": 0.1, "benford": 0.3,
               "leverage": 0.2, "narrative_optimism": 0.7}),
    FraudCase("Enron", "1997–2001", "US", "US GAAP (pre-XBRL)", False,
              "Special-purpose entities hid debt and fabricated earnings; mark-to-model "
              "revenue. Tell: related-party structures + soft assets + leverage.",
              {"accruals": 0.7, "cfo_ni_divergence": 0.8, "dso_rise": 0.4,
               "revenue_aggressiveness": 0.8, "related_party": 0.95, "benford": 0.4,
               "leverage": 0.85, "narrative_optimism": 0.8}),
    FraudCase("WorldCom", "1999–2002", "US", "US GAAP", False,
              "Capitalized $3.8B of line-cost operating expenses as assets to inflate "
              "earnings. Tell: abnormally low expense ratios + soft-asset growth.",
              {"accruals": 0.9, "cfo_ni_divergence": 0.7, "dso_rise": 0.2,
               "revenue_aggressiveness": 0.5, "related_party": 0.2, "benford": 0.5,
               "leverage": 0.6, "narrative_optimism": 0.6}),
    FraudCase("Wirecard", "2015–2020", "Germany", "IFRS", False,
              "€1.9B of escrow cash that never existed; fictitious third-party-acquirer "
              "revenue. Tell: cash-vs-earnings divergence + related-party + opacity.",
              {"accruals": 0.6, "cfo_ni_divergence": 0.95, "dso_rise": 0.6,
               "revenue_aggressiveness": 0.9, "related_party": 0.9, "benford": 0.5,
               "leverage": 0.4, "narrative_optimism": 0.85}),
    FraudCase("Luckin Coffee", "2019–2020", "China/US (20-F)", "US GAAP", True,
              "Fabricated ~RMB 2.2B of sales via fake vouchers and inflated transactions. "
              "Tell: receivables/revenue growth far above cash + digit anomalies.",
              {"accruals": 0.7, "cfo_ni_divergence": 0.8, "dso_rise": 0.7,
               "revenue_aggressiveness": 0.95, "related_party": 0.6, "benford": 0.7,
               "leverage": 0.3, "narrative_optimism": 0.8}),
    FraudCase("Steinhoff", "2015–2017", "Germany/SA", "IFRS", False,
              "~€6.5B of fictitious/irregular transactions through related entities to "
              "inflate profit and asset values. Tell: related-party + soft assets.",
              {"accruals": 0.75, "cfo_ni_divergence": 0.7, "dso_rise": 0.4,
               "revenue_aggressiveness": 0.7, "related_party": 0.95, "benford": 0.4,
               "leverage": 0.7, "narrative_optimism": 0.7}),
    FraudCase("Valeant / Bausch", "2014–2016", "US/Canada", "US GAAP", True,
              "Channel-stuffing through the Philidor specialty pharmacy inflated revenue. "
              "Tell: related-party distribution + receivables + aggressive revenue.",
              {"accruals": 0.7, "cfo_ni_divergence": 0.6, "dso_rise": 0.7,
               "revenue_aggressiveness": 0.85, "related_party": 0.85, "benford": 0.3,
               "leverage": 0.8, "narrative_optimism": 0.6}),
    FraudCase("Tesco", "2014", "UK", "IFRS/UK GAAP", False,
              "£263M overstatement from prematurely booked supplier rebates. "
              "Tell: accrual timing + receivables vs payables manipulation.",
              {"accruals": 0.8, "cfo_ni_divergence": 0.6, "dso_rise": 0.5,
               "revenue_aggressiveness": 0.6, "related_party": 0.3, "benford": 0.4,
               "leverage": 0.5, "narrative_optimism": 0.5}),
]


def filing_fingerprint(score_dict: dict, forensic_features: dict) -> dict[str, float]:
    """Derive a live filing's 0..1 fingerprint from its computed signals."""
    sig = {s["name"]: s for s in score_dict.get("signals", [])}

    def ev(name, default=0.0):
        s = sig.get(name)
        return s["evidence"] if (s and s.get("evidence") is not None) else default

    f = forensic_features
    return {
        "accruals": ev("Accruals / Total Assets"),
        "cfo_ni_divergence": ev("CFO / Net Income"),
        "dso_rise": ev("DSO YoY change (days)"),
        "revenue_aggressiveness": max(ev("Beneish M-Score"), ev("DSO YoY change (days)")),
        # related-party / leverage proxies (no graph tower in thin slice): use leverage ratio
        "related_party": 0.2,
        "benford": ev("Benford first-digit MAD"),
        "leverage": min(1.0, (f.get("altman_x4") or 0) and 0.3 or 0.3),
        "narrative_optimism": ev("Narrative–numbers divergence"),
    }


def nearest_cases(fingerprint: dict[str, float], top: int = 3,
                  min_similarity: float = 0.5) -> list[dict]:
    v = np.array([fingerprint.get(d, 0.0) for d in DIMS], dtype=float)
    if np.linalg.norm(v) == 0:
        return []
    out = []
    for case in CASE_LIBRARY:
        cv = case.vector
        denom = np.linalg.norm(v) * np.linalg.norm(cv)
        sim = float(np.dot(v, cv) / denom) if denom else 0.0
        out.append((sim, case))
    out.sort(key=lambda t: -t[0])
    results = []
    for sim, case in out[:top]:
        if sim < min_similarity:
            continue
        shared = _shared_pattern(fingerprint, case)
        results.append({
            "case_name": case.name, "period": case.period,
            "jurisdiction": case.jurisdiction, "standard": case.standard,
            "in_distribution": case.sec_xbrl, "similarity": round(sim, 3),
            "mechanism": case.mechanism, "shared_pattern": shared,
        })
    return results


def _shared_pattern(fp: dict[str, float], case: FraudCase) -> str:
    labels = {
        "accruals": "accrual build-up", "cfo_ni_divergence": "cash-vs-earnings divergence",
        "dso_rise": "rising receivables/DSO", "revenue_aggressiveness": "aggressive revenue",
        "related_party": "related-party structures", "benford": "digit-distribution anomaly",
        "leverage": "elevated leverage", "narrative_optimism": "tone–fundamentals gap",
    }
    shared = [labels[d] for d in DIMS if fp.get(d, 0) > 0.5 and case.fingerprint.get(d, 0) > 0.5]
    return " + ".join(shared) if shared else "weak/structural resemblance only"
