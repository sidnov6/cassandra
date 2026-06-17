"""Turn SEC `companyfacts` JSON into a clean, point-in-time annual financials panel.

Two engineering hazards the blueprint calls out (§3.2, §5.1) are handled here:

1. Taxonomy evolution — the same economic concept is tagged under different us-gaap
   names across years/filers (e.g. ``Revenues`` vs ``RevenueFromContractWithCustomer...``).
   We resolve each canonical concept against an *ordered alias list*.

2. As-filed, not as-restated — ``companyfacts`` returns every historical fact, including
   the same period re-reported (and possibly restated) as a comparative in later filings.
   For each fiscal-year-end we select the value **as originally filed**: the earliest-filed
   non-amended ``10-K`` fact for that period. Later restatements (filed later) are ignored;
   amendments (10-K/A) are only used as a last resort and flagged.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

# Canonical concept -> ordered alias list (first match wins). 'instant' = balance-sheet.
CONCEPTS: dict[str, dict] = {
    # --- income statement (duration) ---
    "revenue": {"instant": False, "tags": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax"]},
    "cogs": {"instant": False, "tags": [
        "CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"]},
    "gross_profit": {"instant": False, "tags": ["GrossProfit"]},
    "sga": {"instant": False, "tags": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
        "SellingGeneralAndAdministrativeExpenses"]},
    "operating_income": {"instant": False, "tags": ["OperatingIncomeLoss"]},
    "net_income": {"instant": False, "tags": ["NetIncomeLoss", "ProfitLoss"]},
    "dep_amort": {"instant": False, "tags": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization", "Depreciation"]},
    "cfo": {"instant": False, "tags": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]},
    "interest_expense": {"instant": False, "tags": [
        "InterestExpense", "InterestAndDebtExpense"]},
    "income_tax": {"instant": False, "tags": ["IncomeTaxExpenseBenefit"]},
    # --- balance sheet (instant) ---
    "assets": {"instant": True, "tags": ["Assets"]},
    "assets_current": {"instant": True, "tags": ["AssetsCurrent"]},
    "liabilities": {"instant": True, "tags": ["Liabilities"]},
    "liabilities_current": {"instant": True, "tags": ["LiabilitiesCurrent"]},
    "receivables": {"instant": True, "tags": [
        "AccountsReceivableNetCurrent", "ReceivablesNetCurrent",
        "AccountsAndOtherReceivablesNetCurrent"]},
    "inventory": {"instant": True, "tags": ["InventoryNet"]},
    "ppe_net": {"instant": True, "tags": ["PropertyPlantAndEquipmentNet"]},
    "retained_earnings": {"instant": True, "tags": [
        "RetainedEarningsAccumulatedDeficit"]},
    "equity": {"instant": True, "tags": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]},
    "cash": {"instant": True, "tags": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]},
    "long_term_debt": {"instant": True, "tags": [
        "LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"]},
    "working_capital_assets": {"instant": True, "tags": ["AssetsCurrent"]},  # alias for clarity
}

ANNUAL_MIN_DAYS, ANNUAL_MAX_DAYS = 330, 400


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _valid_facts(facts: list[dict], instant: bool) -> dict[str, list[dict]]:
    """Group annual (10-K / 10-K/A) facts by fiscal-year-end after instant/duration filtering.

    Quarter-end balance sheets reported solely in 10-Qs and quarterly/stub durations are
    dropped, so only fiscal-year rows survive. Selection of the as-originally-filed value is
    done separately (accession-pinned in build_panel), NOT here."""
    by_end: dict[str, list[dict]] = {}
    for f in facts:
        end = f.get("end")
        start = f.get("start")
        if end is None or f.get("form") not in ("10-K", "10-K/A"):
            continue
        if instant:
            if start is not None:  # an instant concept only takes point-in-time facts
                continue
        else:
            if start is None:
                continue
            try:
                days = (_d(end) - _d(start)).days
            except ValueError:
                continue
            if not (ANNUAL_MIN_DAYS <= days <= ANNUAL_MAX_DAYS):
                continue
        by_end.setdefault(end, []).append(f)
    return by_end


def _original_filing_per_end(concept_valid: dict[str, dict[str, list[dict]]]) -> dict[str, dict]:
    """For each fiscal-year-end, the ORIGINAL annual filing = the earliest-filed 10-K
    reporting that period (10-K preferred over 10-K/A). Used to pin every concept to the
    as-originally-filed accession, so a later restated comparative cannot leak in."""
    orig: dict[str, dict] = {}
    for vmap in concept_valid.values():
        for end, facts in vmap.items():
            for f in facts:
                is_amend = f.get("form") == "10-K/A"
                rank = (1 if is_amend else 0, f.get("filed", "9999"))  # 10-K, earliest first
                cur = orig.get(end)
                if cur is None or rank < cur["_rank"]:
                    orig[end] = {"accn": f.get("accn"), "filed": f.get("filed"),
                                 "is_amendment": is_amend, "_rank": rank}
    return orig


@dataclasses.dataclass
class FinancialsPanel:
    """Annual financials, one row per fiscal year (ascending), point-in-time."""
    entity: str
    cik: str
    df: pd.DataFrame                     # index = fiscal_year_end (date), columns = concepts
    provenance: dict                      # concept -> {fye -> {accn, form, filed, tag}}

    @property
    def years(self) -> list[date]:
        return list(self.df.index)

    @property
    def fiscal_years(self) -> list[int]:
        return [d.year for d in self.df.index]

    def latest_fye(self) -> Optional[date]:
        return self.df.index[-1] if len(self.df) else None

    def row(self, fye: date) -> pd.Series:
        return self.df.loc[fye]

    def get(self, concept: str, fye: date) -> Optional[float]:
        if concept not in self.df.columns or fye not in self.df.index:
            return None
        v = self.df.at[fye, concept]
        return None if pd.isna(v) else float(v)

    def prior(self, fye: date) -> Optional[date]:
        idx = list(self.df.index)
        i = idx.index(fye)
        return idx[i - 1] if i > 0 else None

    def accession_for(self, fye: date) -> Optional[str]:
        """Accession of the original 10-K that reported this fiscal year (best effort)."""
        for concept in ("assets", "net_income", "revenue"):
            prov = self.provenance.get(concept, {})
            if fye.isoformat() in prov:
                return prov[fye.isoformat()].get("accn")
        return None


def build_panel(facts_json: dict, max_years: int = 16) -> FinancialsPanel:
    """Construct a FinancialsPanel from a companyfacts JSON payload."""
    entity = facts_json.get("entityName", "")
    cik = str(facts_json.get("cik", "")).zfill(10)
    usgaap = facts_json.get("facts", {}).get("us-gaap", {})

    # concept -> {fye_iso -> chosen_fact}
    # Pass 1: validity-filter each concept's annual facts (no selection yet).
    concept_valid: dict[str, dict[str, list[dict]]] = {}
    for concept, spec in CONCEPTS.items():
        merged: list[dict] = []
        for tag in spec["tags"]:
            node = usgaap.get(tag)
            if not node:
                continue
            units = node.get("units", {})
            facts = units.get("USD") or units.get("USD/shares") or []
            for f in facts:
                f = dict(f)
                f["_tag"] = tag
                merged.append(f)
        if merged:
            concept_valid[concept] = _valid_facts(merged, spec["instant"])

    # Pass 2: pin every concept to the ORIGINAL filing's accession per fiscal-year-end. A
    # concept not tagged in the original 10-K is left absent (NaN) rather than backfilled
    # from a later restatement — preserving the as-originally-filed guarantee (§3.2, §7).
    original = _original_filing_per_end(concept_valid)
    concept_vals: dict[str, dict[str, dict]] = {}
    for concept, vmap in concept_valid.items():
        sel: dict[str, dict] = {}
        for end, facts in vmap.items():
            target = original.get(end)
            if not target:
                continue
            match = next((f for f in facts if f.get("accn") == target["accn"]), None)
            if match is not None:
                match = dict(match)
                match["_is_amendment"] = target["is_amendment"]
                sel[end] = match
        concept_vals[concept] = sel

    # Determine fiscal-year-end anchor dates: union of dates where a core concept exists.
    anchor_dates: set[str] = set()
    for anchor in ("assets", "net_income", "revenue", "equity"):
        anchor_dates |= set(concept_vals.get(anchor, {}).keys())
    fye_sorted = sorted(_d(s) for s in anchor_dates)
    if max_years and len(fye_sorted) > max_years:
        fye_sorted = fye_sorted[-max_years:]

    # Build dataframe
    rows = {}
    provenance: dict[str, dict] = {c: {} for c in concept_vals}
    for fye in fye_sorted:
        key = fye.isoformat()
        row = {}
        for concept, chosen in concept_vals.items():
            fact = chosen.get(key)
            if fact is not None:
                row[concept] = fact.get("val")
                provenance[concept][key] = {
                    "accn": fact.get("accn"), "form": fact.get("form"),
                    "filed": fact.get("filed"), "tag": fact.get("_tag"),
                    "is_amendment": fact.get("_is_amendment", False),
                }
            else:
                row[concept] = np.nan
        rows[fye] = row

    df = pd.DataFrame.from_dict(rows, orient="index")
    df = df.reindex(columns=list(CONCEPTS.keys()))
    df.index.name = "fiscal_year_end"
    return FinancialsPanel(entity=entity, cik=cik, df=df, provenance=provenance)


def numeric_population_for_accession(facts_json: dict, accession: str) -> list[float]:
    """All reported us-gaap USD numbers tied to a given accession (for Benford tests)."""
    usgaap = facts_json.get("facts", {}).get("us-gaap", {})
    vals: list[float] = []
    for node in usgaap.values():
        for unit_facts in node.get("units", {}).values():
            for f in unit_facts:
                if f.get("accn") == accession and isinstance(f.get("val"), (int, float)):
                    v = abs(float(f["val"]))
                    if v > 0:
                        vals.append(v)
    return vals
