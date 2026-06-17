"""Challenger / red-team agent (blueprint §6.4). For each flag, construct the strongest
good-faith benign explanation and compute the residual concern that survives it.

This loop is what controls false positives — the dossier ranks by residual_concern, not by
the raw flag severity.
"""
from __future__ import annotations

import json
from typing import Optional

from .llm import call_json, llm_available
from .prompts import CHALLENGER_SYSTEM
from .schema import Flag, Rebuttal

# Per-flag benign templates a competent CFO would offer.
_BENIGN = {
    "REV-1": ("A shift toward larger enterprise deals or a fast-growing segment can extend "
              "receivables and DSO without any manipulation; revenue can be perfectly valid."),
    "ACC-1": ("Accrual spikes can reflect a legitimate acquisition, a build-up of deferred "
              "revenue, or seasonal working-capital swings rather than earnings management."),
    "CF-1": ("Heavy but value-creating investment in working capital (inventory ahead of a "
             "launch, receivables from genuine sales) can depress operating cash flow short-term."),
    "BEN-1": ("Filing-level XBRL contains many structured, rounded, and derived figures, which "
              "naturally breaks strict Benford conformity even with honest books."),
    "GOV-1": ("Distress can be cyclical or sector-wide and does not by itself imply any "
              "manipulation; many distressed firms report scrupulously."),
    "LANG-1": ("Legal and IR teams drive boilerplate, hedging, and complexity in disclosures; "
               "language drift can simply reflect new regulation or a new writer."),
}


def _residual(flag: Flag, corroboration: int) -> float:
    """Risk surviving the charitable reading. More corroborating flags => benign reading
    is weaker => higher residual. A lone flag is heavily discounted."""
    benign_strength = 0.65 if corroboration <= 1 else (0.45 if corroboration == 2 else 0.25)
    residual = flag.severity * flag.confidence * (1.0 - benign_strength)
    # corroboration bonus: independent signals reinforcing each other
    residual *= (1.0 + 0.18 * max(0, corroboration - 1))
    return max(0.0, min(1.0, residual))


def _deterministic_rebuttals(flags: list[Flag]) -> list[Rebuttal]:
    corroboration = len(flags)
    out = []
    for fl in flags:
        benign = _BENIGN.get(fl.flag_id, _BENIGN.get(fl.flag_id.split("-")[0] + "-1",
                  "There may be a legitimate operating explanation for this pattern."))
        out.append(Rebuttal(
            flag_id=fl.flag_id, benign_explanation=benign,
            residual_concern=_residual(fl, corroboration),
            evidence_refs=fl.evidence_refs,
        ))
    return out


def run_challenger(flags: list[Flag], ctx: dict) -> list[Rebuttal]:
    if not flags:
        return []
    if llm_available():
        payload = [fl.to_dict() for fl in flags]
        user = ("For each flag below, return a JSON array of Rebuttal objects with keys "
                "flag_id, benign_explanation, residual_concern (0..1), evidence_refs.\n\n"
                "FLAGS:\n" + json.dumps(payload))
        data = call_json(CHALLENGER_SYSTEM, user)
        if isinstance(data, list) and data:
            by_id = {fl.flag_id: fl for fl in flags}
            out = []
            for d in data:
                fid = str(d.get("flag_id", ""))
                if fid not in by_id:
                    continue
                try:
                    out.append(Rebuttal(
                        flag_id=fid, benign_explanation=str(d.get("benign_explanation", "")),
                        residual_concern=float(d.get("residual_concern", 0.3)),
                        evidence_refs=[str(r) for r in d.get("evidence_refs",
                                                             by_id[fid].evidence_refs)],
                    ))
                except Exception:
                    continue
            if out:
                return out
    return _deterministic_rebuttals(flags)
