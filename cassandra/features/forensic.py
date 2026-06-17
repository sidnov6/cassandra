"""Forensic ratio battery (blueprint §5.2) — the honest, transparent core.

Every formula below is implemented as published and each *component* is exposed as its
own feature (not just the composite), so a downstream model can reweight them. Where a
canonical model needs inputs finer-grained than XBRL reliably provides, we use a
documented operationalization and say so in the code — intellectual honesty is the brand.

References:
  * Beneish (1999) — M-Score (8 components; M > -1.78 flags likely manipulator)
  * Altman (1968)  — Z-Score (manufacturing form)
  * Dechow, Ge, Larson & Sloan (2011) — F-Score (Model 1, Table 7)
  * Sloan (1996) / Dechow et al — accruals & CFO-NI divergence
"""
from __future__ import annotations

import dataclasses
import math
from datetime import date
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..ingest.xbrl import FinancialsPanel
from .benford import BenfordResult


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0 or not math.isfinite(b):
        return None
    return a / b


def _g(panel: FinancialsPanel, concept: str, fye: date) -> Optional[float]:
    return panel.get(concept, fye)


# Beneish coefficients (1999).
_BENEISH = dict(c=-4.84, dsri=0.920, gmi=0.528, aqi=0.404, sgi=0.892,
                depi=0.115, sgai=-0.172, tata=4.679, lvgi=-0.327)


@dataclasses.dataclass
class ForensicReport:
    fye: date
    fiscal_year: int
    accession: Optional[str]
    features: dict[str, Any]          # flat name -> value (and *_note metadata)
    interpretations: dict[str, str]   # human-legible reading per signal family
    series: pd.DataFrame              # per-year trends (m_score, accruals_ta, dso, dsi, ...)
    benford: Optional[BenfordResult] = None

    def to_dict(self) -> dict:
        ser = self.series.copy()
        ser.index = [d.isoformat() for d in ser.index]
        return {
            "fye": self.fye.isoformat(),
            "fiscal_year": self.fiscal_year,
            "accession": self.accession,
            "features": {k: (None if (isinstance(v, float) and not math.isfinite(v)) else v)
                         for k, v in self.features.items()},
            "interpretations": self.interpretations,
            # NaN -> None explicitly: assigning None into a float Series coerces back to NaN,
            # which then serializes as the invalid JSON token `NaN` and breaks browser parsing.
            "series": {col: [None if pd.isna(v) else float(v) for v in ser[col]]
                       for col in ser.columns} | {"fye": list(ser.index)},
            "benford": self.benford.to_dict() if self.benford else None,
        }


# --------------------------------------------------------------------------- components
def beneish_components(panel: FinancialsPanel, t: date, tm1: date) -> dict[str, Optional[float]]:
    g = lambda c, y: _g(panel, c, y)
    out: dict[str, Optional[float]] = {}

    rev_t, rev_p = g("revenue", t), g("revenue", tm1)
    ar_t, ar_p = g("receivables", t), g("receivables", tm1)
    out["DSRI"] = _safe_div(_safe_div(ar_t, rev_t), _safe_div(ar_p, rev_p))

    cogs_t, cogs_p = g("cogs", t), g("cogs", tm1)
    gm_t = _safe_div((rev_t - cogs_t) if (rev_t is not None and cogs_t is not None) else None, rev_t)
    gm_p = _safe_div((rev_p - cogs_p) if (rev_p is not None and cogs_p is not None) else None, rev_p)
    out["GMI"] = _safe_div(gm_p, gm_t)

    def asset_quality(y):
        ca, ppe, ta = g("assets_current", y), g("ppe_net", y), g("assets", y)
        if None in (ca, ppe, ta) or ta == 0:
            return None
        return 1 - (ca + ppe) / ta
    aq_t, aq_p = asset_quality(t), asset_quality(tm1)
    out["AQI"] = _safe_div(aq_t, aq_p)

    out["SGI"] = _safe_div(rev_t, rev_p)

    def dep_rate(y):
        dep, ppe = g("dep_amort", y), g("ppe_net", y)
        if dep is None or ppe is None or (dep + ppe) == 0:
            return None
        return dep / (dep + ppe)
    dr_t, dr_p = dep_rate(t), dep_rate(tm1)
    out["DEPI"] = _safe_div(dr_p, dr_t)

    sga_t, sga_p = g("sga", t), g("sga", tm1)
    out["SGAI"] = _safe_div(_safe_div(sga_t, rev_t), _safe_div(sga_p, rev_p))

    def leverage(y):
        cl, ltd, ta = g("liabilities_current", y), g("long_term_debt", y), g("assets", y)
        if ta is None or ta == 0:
            return None
        num = (cl or 0) + (ltd or 0)
        return num / ta
    lev_t, lev_p = leverage(t), leverage(tm1)
    out["LVGI"] = _safe_div(lev_t, lev_p)

    # TATA via the income-statement operationalization: (NI - CFO) / Total Assets.
    ni_t, cfo_t, ta_t = g("net_income", t), g("cfo", t), g("assets", t)
    if None not in (ni_t, cfo_t, ta_t) and ta_t != 0:
        out["TATA"] = (ni_t - cfo_t) / ta_t
    else:
        out["TATA"] = None
    return out


def beneish_m(components: dict[str, Optional[float]]) -> Optional[float]:
    """Composite M-Score. Missing components default to their 'neutral' index value (1.0,
    or 0.0 for TATA) so a partial computation still yields a usable score (graceful degrade)."""
    neutral = dict(DSRI=1, GMI=1, AQI=1, SGI=1, DEPI=1, SGAI=1, LVGI=1, TATA=0)
    if all(components.get(k) is None for k in neutral):
        return None
    v = {k: (components.get(k) if components.get(k) is not None else neutral[k]) for k in neutral}
    b = _BENEISH
    return (b["c"] + b["dsri"]*v["DSRI"] + b["gmi"]*v["GMI"] + b["aqi"]*v["AQI"]
            + b["sgi"]*v["SGI"] + b["depi"]*v["DEPI"] + b["sgai"]*v["SGAI"]
            + b["tata"]*v["TATA"] + b["lvgi"]*v["LVGI"])


def altman_z(panel: FinancialsPanel, t: date) -> dict[str, Optional[float]]:
    g = lambda c: _g(panel, c, t)
    ta = g("assets")
    ca, cl = g("assets_current"), g("liabilities_current")
    re = g("retained_earnings")
    ebit = g("operating_income")
    if ebit is None:  # EBIT fallback = NI + interest + tax
        ni, ie, tax = g("net_income"), g("interest_expense"), g("income_tax")
        if ni is not None:
            ebit = ni + (ie or 0) + (tax or 0)
    equity, liab = g("equity"), g("liabilities")
    rev = g("revenue")

    x1 = _safe_div((ca - cl) if (ca is not None and cl is not None) else None, ta)
    x2 = _safe_div(re, ta)
    x3 = _safe_div(ebit, ta)
    # X4 uses MARKET equity in the canonical model; thin slice has no price feed, so we use
    # book equity and label it. (Upgrade: wire a price source -> true Z.)
    x4 = _safe_div(equity, liab)
    x5 = _safe_div(rev, ta)
    parts = dict(X1=x1, X2=x2, X3=x3, X4=x4, X5=x5)
    if any(v is None for v in parts.values()):
        z = None
    else:
        z = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5
    parts["Z"] = z
    parts["_x4_note"] = "book-equity proxy (market cap unavailable in thin slice)"
    return parts


def dechow_fscore(panel: FinancialsPanel, t: date, tm1: date) -> dict[str, Optional[float]]:
    """Dechow et al. (2011) Model 1. Several inputs are operationalized from available XBRL
    tags (noted); the exact RSST accrual needs finer working-capital decomposition."""
    g = lambda c, y: _g(panel, c, y)
    ta_t, ta_p = g("assets", t), g("assets", tm1)
    avg_ta = ((ta_t or 0) + (ta_p or 0)) / 2 if (ta_t and ta_p) else ta_t
    if not avg_ta:
        return {"f_score": None}

    ni_t, cfo_t = g("net_income", t), g("cfo", t)
    rsst = _safe_div((ni_t - cfo_t) if (ni_t is not None and cfo_t is not None) else None, avg_ta)  # accrual proxy

    ar_t, ar_p = g("receivables", t), g("receivables", tm1)
    ch_rec = _safe_div((ar_t - ar_p) if (ar_t is not None and ar_p is not None) else None, avg_ta)
    inv_t, inv_p = g("inventory", t), g("inventory", tm1)
    ch_inv = _safe_div((inv_t - inv_p) if (inv_t is not None and inv_p is not None) else None, avg_ta)

    ppe_t, cash_t = g("ppe_net", t), g("cash", t)
    soft = _safe_div((ta_t - (ppe_t or 0) - (cash_t or 0)) if ta_t is not None else None, ta_t)

    rev_t, rev_p = g("revenue", t), g("revenue", tm1)
    cs_t = (rev_t - ((ar_t or 0) - (ar_p or 0))) if rev_t is not None else None
    cs_p = rev_p
    ch_cash_sales = _safe_div((cs_t - cs_p) if (cs_t is not None and cs_p is not None) else None, cs_p)

    roa_t = _safe_div(ni_t, ta_t)
    roa_p = _safe_div(g("net_income", tm1), ta_p)
    ch_roa = (roa_t - roa_p) if (roa_t is not None and roa_p is not None) else None

    # Issuance proxy: long-term debt increased OR equity rose beyond retained earnings.
    ltd_t, ltd_p = g("long_term_debt", t), g("long_term_debt", tm1)
    issuance = 1.0 if (ltd_t is not None and ltd_p is not None and ltd_t > ltd_p * 1.05) else 0.0

    def z(v):  # treat missing as 0 (neutral) for the linear index
        return v if v is not None else 0.0
    predicted = (-7.893 + 0.790*z(rsst) + 2.518*z(ch_rec) + 1.191*z(ch_inv)
                 + 1.979*z(soft) + 0.171*z(ch_cash_sales) - 0.932*z(ch_roa)
                 + 1.029*issuance)
    prob = 1 / (1 + math.exp(-predicted))
    f = prob / 0.0037  # scale by unconditional misstatement rate
    return {"f_score": f, "f_prob": prob, "rsst_accruals": rsst, "ch_receivables": ch_rec,
            "ch_inventory": ch_inv, "pct_soft_assets": soft, "ch_cash_sales": ch_cash_sales,
            "ch_roa": ch_roa, "issuance": issuance}


def _accruals_and_divergence(panel: FinancialsPanel, t: date) -> dict[str, Optional[float]]:
    g = lambda c: _g(panel, c, t)
    ni, cfo, ta = g("net_income"), g("cfo"), g("assets")
    accr = (ni - cfo) if (ni is not None and cfo is not None) else None
    return {
        "ni": ni, "cfo": cfo,
        "ni_minus_cfo": accr,
        "accruals_to_ta": _safe_div(accr, ta),
        "cfo_ni_ratio": _safe_div(cfo, ni),
    }


def _dso_dsi(panel: FinancialsPanel, t: date) -> dict[str, Optional[float]]:
    g = lambda c: _g(panel, c, t)
    rev, ar, cogs, inv = g("revenue"), g("receivables"), g("cogs"), g("inventory")
    dso_r, dsi_r = _safe_div(ar, rev), _safe_div(inv, cogs)
    return {
        "dso": None if dso_r is None else dso_r * 365,
        "dsi": None if dsi_r is None else dsi_r * 365,
    }


# --------------------------------------------------------------------------- driver
def compute_forensic(panel: FinancialsPanel,
                     benford: Optional[BenfordResult] = None,
                     target_fye: Optional[date] = None) -> Optional[ForensicReport]:
    """Score a single filing. `target_fye` selects the fiscal year to score (point-in-time);
    defaults to the most recent. The per-year trend series is always computed in full."""
    fyes = panel.years
    if len(fyes) < 1:
        return None
    t = target_fye if (target_fye in fyes) else fyes[-1]
    tm1 = panel.prior(t)

    # ---- per-year trend series (for temporal tower + UI trend chart) ----
    rows = {}
    for i, y in enumerate(fyes):
        yp = fyes[i - 1] if i > 0 else None
        comp = beneish_components(panel, y, yp) if yp else {}
        m = beneish_m(comp) if yp else None
        acc = _accruals_and_divergence(panel, y)
        dd = _dso_dsi(panel, y)
        fs = dechow_fscore(panel, y, yp) if yp else {"f_score": None}
        rows[y] = {
            "m_score": m,
            "f_score": fs.get("f_score"),
            "accruals_to_ta": acc["accruals_to_ta"],
            "ni_minus_cfo": acc["ni_minus_cfo"],
            "dso": dd["dso"], "dsi": dd["dsi"],
            "dsri": comp.get("DSRI"),
            "revenue": panel.get("revenue", y),
        }
    series = pd.DataFrame.from_dict(rows, orient="index")
    series.index.name = "fye"

    # ---- latest-year feature vector ----
    comp = beneish_components(panel, t, tm1) if tm1 else {}
    m = beneish_m(comp) if tm1 else None
    z = altman_z(panel, t)
    fs = dechow_fscore(panel, t, tm1) if tm1 else {"f_score": None}
    acc = _accruals_and_divergence(panel, t)
    dd = _dso_dsi(panel, t)

    # YoY deltas on DSO/DSI (the escalation tell), anchored to the target year t.
    dso_prev = series["dso"].loc[tm1] if (tm1 is not None and tm1 in series.index) else None
    dsi_prev = series["dsi"].loc[tm1] if (tm1 is not None and tm1 in series.index) else None
    dso_delta = (dd["dso"] - dso_prev) if (dd["dso"] is not None and dso_prev is not None and pd.notna(dso_prev)) else None
    dsi_delta = (dd["dsi"] - dsi_prev) if (dd["dsi"] is not None and dsi_prev is not None and pd.notna(dsi_prev)) else None

    features: dict[str, Any] = {
        "beneish_m": m,
        **{f"beneish_{k.lower()}": v for k, v in comp.items()},
        "altman_z": z["Z"], "altman_x1": z["X1"], "altman_x2": z["X2"],
        "altman_x3": z["X3"], "altman_x4": z["X4"], "altman_x5": z["X5"],
        "altman_x4_note": z["_x4_note"],
        "dechow_f": fs.get("f_score"), "dechow_f_prob": fs.get("f_prob"),
        "rsst_accruals": fs.get("rsst_accruals"),
        "ni": acc["ni"], "cfo": acc["cfo"], "ni_minus_cfo": acc["ni_minus_cfo"],
        "accruals_to_ta": acc["accruals_to_ta"], "cfo_ni_ratio": acc["cfo_ni_ratio"],
        "dso": dd["dso"], "dsi": dd["dsi"],
        "dso_yoy_delta": dso_delta, "dsi_yoy_delta": dsi_delta,
        "benford_mad": benford.mad if benford else None,
        "benford_conformity": benford.conformity if benford else None,
        "benford_anomaly": benford.anomaly_score if benford else None,
    }

    interpretations = {
        "beneish": _interp_beneish(m),
        "altman": _interp_altman(z["Z"]),
        "dechow": _interp_dechow(fs.get("f_score")),
        "accruals": _interp_accruals(acc, dso_delta),
        "benford": (f"First-digit MAD {benford.mad:.4f} → {benford.conformity}."
                    if benford else "Insufficient numeric population for Benford."),
    }

    return ForensicReport(fye=t, fiscal_year=t.year, accession=panel.accession_for(t),
                          features=features, interpretations=interpretations,
                          series=series, benford=benford)


def _yoy(s: pd.Series) -> Optional[float]:
    s = s.dropna()
    if len(s) < 2 or s.iloc[-2] == 0:
        return None
    return (s.iloc[-1] - s.iloc[-2]) / abs(s.iloc[-2])


# --------------------------------------------------------------------------- interpretations
def _interp_beneish(m: Optional[float]) -> str:
    if m is None:
        return "M-Score unavailable (need two consecutive years)."
    verdict = "above the -1.78 manipulation threshold" if m > -1.78 else "below the -1.78 threshold"
    return f"Beneish M = {m:.2f}, {verdict}."


def _interp_altman(z: Optional[float]) -> str:
    if z is None:
        return "Z-Score unavailable."
    zone = "distress (<1.81)" if z < 1.81 else ("grey (1.81–2.99)" if z < 2.99 else "safe (>2.99)")
    return f"Altman Z = {z:.2f} → {zone}."


def _interp_dechow(f: Optional[float]) -> str:
    if f is None:
        return "F-Score unavailable."
    band = ("substantial risk (>2.45)" if f > 2.45 else
            "above-normal risk (>1.0)" if f > 1.0 else "near/below normal (≤1.0)")
    return f"Dechow F = {f:.2f} → {band}."


def _interp_accruals(acc: dict, dso_delta: Optional[float]) -> str:
    bits = []
    if acc["ni_minus_cfo"] is not None:
        sign = "exceeds" if acc["ni_minus_cfo"] > 0 else "trails"
        bits.append(f"Net income {sign} operating cash flow by "
                    f"${abs(acc['ni_minus_cfo'])/1e9:.2f}B (accrual gap).")
    if dso_delta is not None:
        bits.append(f"DSO moved {dso_delta:+.1f} days YoY.")
    return " ".join(bits) or "Accrual signals unavailable."
