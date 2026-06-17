"""Synthesis agent (blueprint §6.4, §12.1). Composes the ranked, audit-grade dossier memo
from flags, rebuttals, analogues, and the calibrated score. Probabilistic language only —
a triage flag, never a verdict.
"""
from __future__ import annotations

import json
from typing import Optional

from .llm import call_text, llm_available
from .prompts import SYNTHESIS_SYSTEM
from .schema import Analogue, Flag, Rebuttal

# Cheapest next-step suggestions keyed by the dominant flag.
_NEXT_STEP = {
    "REV-1": "Reconcile segment-level receivables aging against revenue, and read the "
             "revenue-recognition footnote for any policy loosening this year.",
    "CF-1": "Bridge net income to operating cash flow line by line; isolate the working-capital "
            "items driving the gap and test them against the revenue narrative.",
    "ACC-1": "Decompose accruals into discretionary vs non-discretionary (industry-year Jones "
             "model) and check whether the spike coincides with a guidance miss.",
    "BEN-1": "Re-run Benford on transaction-level or segment detail (not filing-level XBRL) "
             "before weighting the digit anomaly.",
    "GOV-1": "Pull the auditor's report and any going-concern language; check for recent "
             "auditor or CFO changes (8-K 4.01 / 5.02).",
    "LANG-1": "Diff this year's MD&A against last year's and map rewritten passages to the "
              "specific accounts they describe.",
}


def _band_phrase(band: str) -> str:
    return {"ELEVATED": "Elevated manipulation risk", "WATCH": "Watch-list risk",
            "LOW": "Low manipulation risk"}.get(band, "Risk")


def _deterministic_memo(entity: str, fy: int, accession: Optional[str], score: dict,
                        ranked: list[tuple[Flag, Rebuttal]], analogues: list[Analogue]) -> str:
    p = score["calibrated_p"]
    conf = score["confidence"]
    band = score["band"]
    conf_word = "high" if conf >= 0.75 else ("moderate" if conf >= 0.6 else "limited")

    lines = []
    lines.append(f"CASSANDRA Dossier — {entity}, FY{fy} 10-K"
                 + (f" (accession {accession})" if accession else ""))
    lines.append("")
    lines.append(f"Headline: {_band_phrase(band)} — calibrated score {p:.2f} "
                 f"(confidence: {conf_word}). Triage flag, not a determination.")
    lines.append("")

    if not ranked:
        lines.append("No specialist raised a grounded concern at the configured thresholds. "
                     "The forensic ratios, accrual quality, and (where available) disclosure "
                     "language are within normal ranges for this filing. Continue routine "
                     "monitoring; nothing here warrants escalation.")
    else:
        lines.append("Top concerns (ranked by residual concern after the charitable reading):")
        lines.append("")
        for i, (fl, rb) in enumerate(ranked, 1):
            lines.append(f"{i}. [{rb.residual_concern:.2f} residual] {fl.title} — {fl.agent}")
            lines.append(f"   Evidence: {fl.rationale}")
            lines.append(f"   Refs: {', '.join(fl.evidence_refs)}")
            lines.append(f"   Challenger (benign reading): {rb.benign_explanation}")
            lines.append("")

    if analogues:
        a = analogues[0]
        lines.append(f"Nearest historical analogue: pattern resembles {a.case_name} "
                     f"(similarity {a.similarity:.2f}) — shared pattern = {a.shared_pattern}."
                     + (f" {a.note}" if a.note else ""))
        lines.append("")

    if ranked:
        top_id = ranked[0][0].flag_id
        step = _NEXT_STEP.get(top_id, _NEXT_STEP.get(top_id.split("-")[0] + "-1",
                "Request the relevant workpapers and reconcile the flagged accounts to source."))
        lines.append(f"Cheapest next step: {step}")

    return "\n".join(lines)


def run_synthesis(entity: str, fy: int, accession: Optional[str], score: dict,
                  flags: list[Flag], rebuttals: list[Rebuttal],
                  analogues: list[Analogue]) -> str:
    rb_by_id = {r.flag_id: r for r in rebuttals}
    pairs = [(fl, rb_by_id[fl.flag_id]) for fl in flags if fl.flag_id in rb_by_id]
    pairs.sort(key=lambda t: -t[1].residual_concern)

    if llm_available():
        payload = {
            "entity": entity, "fiscal_year": fy, "accession": accession,
            "calibrated_score": score["calibrated_p"], "confidence": score["confidence"],
            "band": score["band"], "contributions": score["contributions"],
            "flags": [fl.to_dict() for fl in flags],
            "rebuttals": [rb.to_dict() for rb in rebuttals],
            "analogues": [a.to_dict() for a in analogues],
        }
        memo = call_text(SYNTHESIS_SYSTEM, "Produce the dossier memo for:\n" + json.dumps(payload))
        if memo and len(memo) > 100:
            return memo.strip()
    return _deterministic_memo(entity, fy, accession, score, pairs, analogues)
