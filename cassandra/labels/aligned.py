"""Align case labels to filings (blueprint §7.1).

A filing for fiscal year Y of firm i is labelled positive iff a known case for firm i has
fraud_start <= Y <= fraud_end (the commission window). Enforcement happens years later and
must never define the label. Returns the `labels_aligned` table per the §5.1 schema.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .known_cases import CaseLabel


def build_labels_aligned(cases: list[CaseLabel]) -> pd.DataFrame:
    rows = []
    for c in cases:
        if not c.cik:
            continue
        rows.append({
            "cik": str(c.cik).zfill(10), "ticker": c.ticker, "name": c.name,
            "fraud_start": c.fraud_start, "fraud_end": c.fraud_end,
            "enforcement_year": c.enforcement_year,
            "label_source": c.source, "label_strength": c.label_strength,
            "standard": c.standard, "sec_xbrl": c.sec_xbrl,
        })
    return pd.DataFrame(rows, columns=[
        "cik", "ticker", "name", "fraud_start", "fraud_end", "enforcement_year",
        "label_source", "label_strength", "standard", "sec_xbrl"])


def label_for_filing(cik: str, fiscal_year: int, labels_aligned: pd.DataFrame
                     ) -> dict:
    """Return {label, in_fraud_period, label_source, label_strength} for a (cik, year)."""
    cik = str(cik).zfill(10)
    hits = labels_aligned[(labels_aligned["cik"] == cik)
                          & (labels_aligned["fraud_start"] <= fiscal_year)
                          & (labels_aligned["fraud_end"] >= fiscal_year)]
    if len(hits):
        r = hits.iloc[0]
        return {"label": 1, "in_fraud_period": True,
                "label_source": r["label_source"], "label_strength": r["label_strength"]}
    # firm is a known filer but this year is outside the window -> still presumed-negative,
    # but we tag it so the trainer can optionally exclude peri-fraud years from the negatives.
    known = (labels_aligned["cik"] == cik).any()
    return {"label": 0, "in_fraud_period": False,
            "label_source": "presumed_clean" if not known else "peri_fraud_year",
            "label_strength": "unlabeled"}
