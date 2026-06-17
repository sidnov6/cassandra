"""Specialist agents (blueprint §6.2). Each runs a deterministic, evidence-grounded rule
engine by default and upgrades to the LLM prompt template when a key is available.

Every flag cites resolvable evidence_refs into the computed features (and text offsets),
honoring the grounding rule so the synthesis step never emits an unsupported claim.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from .llm import call_json, llm_available
from .prompts import SPECIALIST_SYSTEM
from .schema import Flag, evidence_ref


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _fnum(features: dict, key: str):
    v = features.get(key)
    return v if isinstance(v, (int, float)) else None


# --------------------------------------------------------------------------- deterministic
def _revenue(ctx: dict) -> list[Flag]:
    f = ctx["features"]
    flags: list[Flag] = []
    dsri = _fnum(f, "beneish_dsri")
    dso_d = _fnum(f, "dso_yoy_delta")
    cfo_ni = _fnum(f, "cfo_ni_ratio")
    m = _fnum(f, "beneish_m")

    rising_recv = (dsri is not None and dsri > 1.20) or (dso_d is not None and dso_d > 6)
    cash_divergence = cfo_ni is not None and cfo_ni < 0.85
    if rising_recv and (cash_divergence or (m is not None and m > -1.78)):
        sev = _clip(0.45 + (0.3 if cash_divergence else 0) + (0.25 if (m and m > -1.78) else 0))
        bits = []
        if dsri is not None:
            bits.append(f"DSRI={dsri:.2f}")
        if dso_d is not None:
            bits.append(f"DSO {dso_d:+.1f} days YoY")
        if cfo_ni is not None:
            bits.append(f"CFO/NI={cfo_ni:.2f}")
        flags.append(Flag(
            "REV-1", "Revenue-Quality", "Possible premature / aggressive revenue recognition",
            severity=sev, confidence=_clip(0.55 + (0.2 if cash_divergence else 0)),
            rationale=("Receivables are growing faster than the cash they should convert to "
                       f"({', '.join(bits)}). Pattern is consistent with pulling revenue "
                       "forward (channel stuffing / premature recognition)."),
            evidence_refs=[evidence_ref("feature", "beneish_dsri"),
                           evidence_ref("feature", "dso_yoy_delta"),
                           evidence_ref("feature", "cfo_ni_ratio")],
        ))
    return flags


def _accruals(ctx: dict) -> list[Flag]:
    f = ctx["features"]
    flags: list[Flag] = []
    accr = _fnum(f, "accruals_to_ta")
    fscore = _fnum(f, "dechow_f")
    if (accr is not None and accr > 0.05) or (fscore is not None and fscore > 1.5):
        sev = _clip((accr or 0) / 0.12 * 0.6 + (0.4 if (fscore and fscore > 1.5) else 0))
        flags.append(Flag(
            "ACC-1", "Accruals", "Elevated accruals relative to cash earnings",
            severity=_clip(sev, 0.3, 1.0), confidence=0.6,
            rationale=(f"Accruals/Total Assets = {accr:+.3f}" if accr is not None else "")
                      + (f"; Dechow F = {fscore:.2f} (>1 above-average misstatement risk)."
                         if fscore is not None else "."),
            evidence_refs=[evidence_ref("feature", "accruals_to_ta"),
                           evidence_ref("feature", "dechow_f"),
                           evidence_ref("feature", "rsst_accruals")],
        ))
    return flags


def _cashflow(ctx: dict) -> list[Flag]:
    f = ctx["features"]
    flags: list[Flag] = []
    cfo_ni = _fnum(f, "cfo_ni_ratio")
    nimc = _fnum(f, "ni_minus_cfo")
    if cfo_ni is not None and cfo_ni < 0.8:
        sev = _clip(0.4 + (0.8 - cfo_ni) * 0.6)
        direction = "negative" if cfo_ni < 0 else "well below 1.0"
        flags.append(Flag(
            "CF-1", "Cash-Flow Divergence", "Earnings not backed by operating cash flow",
            severity=sev, confidence=0.7,
            rationale=(f"CFO/NI = {cfo_ni:.2f} ({direction}). Reported profit is not "
                       "converting to operating cash — the classic accrual-quality tell."
                       + (f" NI-CFO gap = ${nimc/1e9:.2f}B." if nimc is not None else "")),
            evidence_refs=[evidence_ref("feature", "cfo_ni_ratio"),
                           evidence_ref("feature", "ni_minus_cfo")],
        ))
    return flags


def _benford(ctx: dict) -> list[Flag]:
    bf = ctx.get("benford")
    flags: list[Flag] = []
    if not bf:
        return flags
    # Filing-level XBRL is a small, partly-rounded population, so mild nonconformity is the
    # norm. Only flag a pronounced anomaly (or first-two-digit nonconformity), to avoid the
    # universal false positive.
    if bf.get("conformity") == "nonconformity" and bf.get("anomaly_score", 0.0) > 0.62:
        sev = _clip(bf.get("anomaly_score", 0.0))
        flags.append(Flag(
            "BEN-1", "Benford / Digit", "Digit distribution deviates from Benford's Law",
            severity=sev, confidence=0.4,
            rationale=(f"First-digit MAD = {bf.get('mad'):.4f} -> {bf.get('conformity')} "
                       f"(n={bf.get('n')} reported figures). CAVEAT: filing-level XBRL is a "
                       "small, partly-rounded population, so treat as corroborating, not "
                       "dispositive."),
            evidence_refs=[evidence_ref("feature", "benford_mad"),
                           evidence_ref("benford", "first_digit")],
        ))
    return flags


def _governance(ctx: dict) -> list[Flag]:
    f = ctx["features"]
    flags: list[Flag] = []
    z = _fnum(f, "altman_z")
    if z is not None and z < 1.81:
        flags.append(Flag(
            "GOV-1", "Governance", "Financial-distress zone raises controls/incentive risk",
            severity=_clip((1.81 - z) / 1.81), confidence=0.45,
            rationale=(f"Altman Z = {z:.2f} (<1.81 distress). Distress sharpens management "
                       "incentives to manage earnings. NOTE: board/auditor/related-party graph "
                       "features are out of scope in the thin slice (production adds the GNN tower)."),
            evidence_refs=[evidence_ref("feature", "altman_z")],
        ))
    return flags


def _language(ctx: dict) -> list[Flag]:
    t = ctx.get("text")
    flags: list[Flag] = []
    if not t or not t.get("available"):
        return flags
    hedge = t.get("hedging_score")
    fog = t.get("fog_index")
    shift = t.get("yoy_language_shift")
    div = t.get("narrative_numbers_divergence")
    triggers = []
    if hedge is not None and hedge > 0.50:
        triggers.append(f"hedging density {hedge:.2f}")
    if fog is not None and fog > 27:
        triggers.append(f"Fog index {fog:.1f} (beyond the high 10-K baseline)")
    if shift is not None and shift > 0.6:
        triggers.append(f"MD&A language shifted {shift:.2f} vs prior year")
    if div is not None and div > 0.45:
        triggers.append(f"tone-fundamentals gap {div:+.2f}")
    # 10-Ks are uniformly complex and hedged; require corroboration (>=2 signals) to flag.
    if len(triggers) >= 2:
        refs = [evidence_ref("feature", "hedging_score"), evidence_ref("feature", "fog_index")]
        if t.get("mdna_offsets"):
            a, b = t["mdna_offsets"]
            refs.append(evidence_ref("text", "MDNA", f"{a}-{b}"))
        flags.append(Flag(
            "LANG-1", "Disclosure-Language", "Narrative obfuscation / optimism-fundamentals gap",
            severity=_clip(0.3 + 0.15 * len(triggers)), confidence=0.45,
            rationale="Disclosure-language signals: " + "; ".join(triggers) + ".",
            evidence_refs=refs,
        ))
    return flags


_DETERMINISTIC: dict[str, Callable[[dict], list[Flag]]] = {
    "revenue": _revenue, "accruals": _accruals, "cashflow": _cashflow,
    "benford": _benford, "governance": _governance, "language": _language,
}

AGENT_LABELS = {
    "revenue": "Revenue-Quality Agent", "accruals": "Accruals Agent",
    "cashflow": "Cash-Flow Divergence Agent", "benford": "Benford / Digit Agent",
    "governance": "Governance Agent", "language": "Disclosure-Language Agent",
}


# --------------------------------------------------------------------------- LLM path
def _llm_flags(agent_key: str, ctx: dict) -> Optional[list[Flag]]:
    if not llm_available():
        return None
    context = {
        "features": {k: v for k, v in ctx["features"].items() if isinstance(v, (int, float, str))},
        "benford": ctx.get("benford"),
        "text": ctx.get("text"),
        "interpretations": ctx.get("interpretations"),
    }
    user = ("Analyze this filing's evidence and return a JSON array of Flag objects with keys "
            "flag_id, agent, title, severity (0..1), confidence (0..1), rationale, "
            "evidence_refs (list of strings).\n\nEVIDENCE:\n" + json.dumps(context, default=str))
    data = call_json(SPECIALIST_SYSTEM[agent_key], user)
    if not isinstance(data, list):
        return None
    out: list[Flag] = []
    for i, d in enumerate(data):
        try:
            out.append(Flag(
                flag_id=str(d.get("flag_id") or f"{agent_key[:3].upper()}-{i+1}"),
                agent=AGENT_LABELS[agent_key], title=str(d["title"]),
                severity=float(d.get("severity", 0.5)), confidence=float(d.get("confidence", 0.5)),
                rationale=str(d.get("rationale", "")),
                evidence_refs=[str(r) for r in d.get("evidence_refs", [])],
            ))
        except Exception:
            continue
    return out


def run_specialist(agent_key: str, ctx: dict) -> list[Flag]:
    """Run one specialist: LLM path if available (with deterministic fallback), else rules."""
    flags = _llm_flags(agent_key, ctx)
    if flags is None:
        flags = _DETERMINISTIC[agent_key](ctx)
    for fl in flags:
        fl.agent = AGENT_LABELS[agent_key]
    return flags
