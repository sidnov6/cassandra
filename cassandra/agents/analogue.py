"""Historical-analogue agent (blueprint §6.2). Matches the filing's pattern fingerprint to
the known-case library and returns the nearest analogues, always framed as a *pattern*
resemblance — never an accusation that the filer committed that fraud.
"""
from __future__ import annotations

from ..cases.library import filing_fingerprint, nearest_cases
from .schema import Analogue


def run_analogue(score_dict: dict, forensic_features: dict, top: int = 3) -> list[Analogue]:
    fp = filing_fingerprint(score_dict, forensic_features)
    matches = nearest_cases(fp, top=top, min_similarity=0.55)
    out = []
    for m in matches:
        note = "" if m["in_distribution"] else (
            "Out-of-distribution for the US-XBRL scorer (different regime/standard); "
            "used as a qualitative pattern analogue only.")
        out.append(Analogue(
            case_name=m["case_name"], similarity=m["similarity"],
            shared_pattern=m["shared_pattern"], in_distribution=m["in_distribution"],
            note=note,
        ))
    return out
