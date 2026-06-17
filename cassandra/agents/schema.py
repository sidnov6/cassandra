"""Shared agent state + output schemas (blueprint §6.3).

Grounding rule: every Flag/Rebuttal carries `evidence_refs`. The synthesis step drops any
flag whose references do not resolve. Agents emit structured dicts (validated here), not
free prose, until the final memo.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Optional


@dataclasses.dataclass
class Flag:
    flag_id: str
    agent: str
    title: str
    severity: float            # 0..1 — magnitude of the concern
    confidence: float          # 0..1 — strength of the evidence
    rationale: str
    evidence_refs: list[str]   # resolvable pointers into features / text offsets

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Rebuttal:
    flag_id: str
    benign_explanation: str
    residual_concern: float    # 0..1 — risk surviving the most charitable reading
    evidence_refs: list[str]

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Analogue:
    case_name: str
    similarity: float
    shared_pattern: str
    in_distribution: bool
    note: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Dossier:
    cik: str
    accession: Optional[str]
    entity: str
    fiscal_year: int
    point_in_time: str
    calibrated_score: float
    confidence: float
    band: str
    contributions: dict[str, float]
    flags: list[dict]
    rebuttals: list[dict]
    analogues: list[dict]
    memo: str
    llm_mode: str              # "llm" | "deterministic"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def evidence_ref(kind: str, key: str, extra: str = "") -> str:
    """Build a resolvable evidence reference, e.g. 'feature:beneish_m' or 'text:MDNA:1234-5678'."""
    return f"{kind}:{key}" + (f":{extra}" if extra else "")
