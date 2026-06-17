"""LangGraph implementation of the agent graph (blueprint §6.2).

Same topology and node logic as `orchestrator.py`, expressed as a LangGraph `StateGraph`
for production checkpointing/persistence. Specialists fan out in parallel from the router
and fan in at the collector (a reducer merges their flags); then challenger -> analogue ->
synthesis run sequentially. The streaming SSE path stays on `orchestrator.py`; this is the
durable, framework-native execution the blueprint specifies.
"""
from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict

from .analogue import run_analogue
from .challenger import run_challenger
from .schema import Analogue, Flag, Rebuttal
from .specialists import run_specialist
from .synthesis import run_synthesis
from .llm import llm_available

SPECIALIST_KEYS = ["revenue", "accruals", "cashflow", "benford", "governance", "language"]


class GState(TypedDict, total=False):
    ctx: dict
    score: dict
    flags: Annotated[list, operator.add]   # parallel specialists append; reducer merges
    grounded_flags: list
    rebuttals: list
    analogues: list
    memo: str


def _router(state: GState) -> dict:
    return {}


def _make_specialist(key: str):
    def node(state: GState) -> dict:
        flags = run_specialist(key, state["ctx"])
        return {"flags": [f.to_dict() for f in flags]}
    return node


def _collector(state: GState) -> dict:
    # grounding rule: drop any flag without resolvable evidence_refs
    grounded = [f for f in state.get("flags", []) if f.get("evidence_refs")]
    return {"grounded_flags": grounded}


def _challenger(state: GState) -> dict:
    flags = [Flag(**f) for f in state.get("grounded_flags", [])]
    rebuttals = run_challenger(flags, state["ctx"])
    return {"rebuttals": [r.to_dict() for r in rebuttals]}


def _analogue(state: GState) -> dict:
    analogues = run_analogue(state["score"], state["ctx"]["features"])
    return {"analogues": [a.to_dict() for a in analogues]}


def _synthesis(state: GState) -> dict:
    ctx = state["ctx"]
    flags = [Flag(**f) for f in state.get("grounded_flags", [])]
    rebuttals = [Rebuttal(**r) for r in state.get("rebuttals", [])]
    analogues = [Analogue(**a) for a in state.get("analogues", [])]
    memo = run_synthesis(ctx["entity"], ctx["fiscal_year"], ctx.get("accession"),
                         state["score"], flags, rebuttals, analogues)
    return {"memo": memo}


def build_graph():
    from langgraph.graph import START, END, StateGraph
    g = StateGraph(GState)
    g.add_node("router", _router)
    for k in SPECIALIST_KEYS:
        g.add_node(k, _make_specialist(k))
    g.add_node("collector", _collector)
    g.add_node("challenger", _challenger)
    g.add_node("analogue", _analogue)
    g.add_node("synthesis", _synthesis)

    g.add_edge(START, "router")
    for k in SPECIALIST_KEYS:
        g.add_edge("router", k)
        g.add_edge(k, "collector")
    g.add_edge("collector", "challenger")
    g.add_edge("challenger", "analogue")
    g.add_edge("analogue", "synthesis")
    g.add_edge("synthesis", END)
    return g.compile()


_COMPILED = None


def run_langgraph(ctx: dict, score: dict) -> dict:
    """Execute the LangGraph graph and return the assembled dossier dict."""
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_graph()
    final = _COMPILED.invoke({"ctx": ctx, "score": score, "flags": []})
    return {
        "cik": ctx["cik"], "accession": ctx.get("accession"), "entity": ctx["entity"],
        "fiscal_year": ctx["fiscal_year"], "point_in_time": ctx.get("point_in_time", ""),
        "calibrated_score": score["calibrated_p"], "confidence": score["confidence"],
        "band": score["band"], "contributions": score["contributions"],
        "flags": final.get("grounded_flags", []),
        "rebuttals": final.get("rebuttals", []),
        "analogues": final.get("analogues", []),
        "memo": final.get("memo", ""),
        "llm_mode": "llm" if llm_available() else "deterministic",
        "engine": "langgraph",
    }
