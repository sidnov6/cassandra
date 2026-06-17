"""Agent-graph orchestrator (blueprint §6.2).

Topology:  router -> [6 specialists in parallel] -> collector -> challenger -> analogue -> synthesis

Hand-rolled (zero-dependency) but mirrors the LangGraph graph exactly; production swaps in
LangGraph for checkpointing/persistence. `stream_agent_graph` yields node-activation events
for the live React-Flow journey UI; `run_agent_graph` consumes them and returns the Dossier.
"""
from __future__ import annotations

from typing import Iterator, Optional

from .analogue import run_analogue
from .challenger import run_challenger
from .schema import Dossier
from .specialists import AGENT_LABELS, run_specialist
from .synthesis import run_synthesis
from .llm import llm_available

# Node ids used by the UI graph (order defines the journey).
SPECIALIST_KEYS = ["revenue", "accruals", "cashflow", "benford", "governance", "language"]
GRAPH_NODES = ["router", *SPECIALIST_KEYS, "collector", "challenger", "analogue", "synthesis"]


def _ev(node: str, status: str, msg: str = "", payload: Optional[dict] = None) -> dict:
    return {"node": node, "status": status, "msg": msg, "payload": payload or {}}


def stream_agent_graph(ctx: dict, score: dict) -> Iterator[dict]:
    """Yield {node, status, msg, payload} events as the graph executes, then a final
    {node:'__final__'} event carrying the assembled dossier dict."""
    mode = "llm" if llm_available() else "deterministic"
    yield _ev("router", "running", f"Routing filing into the specialist graph ({mode} mode).")

    # Router uses model scores as priors: emphasize specialists whose modality scored high.
    contrib = score.get("contributions", {})
    priors = ", ".join(f"{k}:{v:.0%}" for k, v in sorted(contrib.items(), key=lambda t: -t[1]))
    yield _ev("router", "done", f"Modality priors → {priors or 'n/a'}. Dispatching specialists.")

    # ---- specialists (parallel in spirit; grounded flags) ----
    all_flags = []
    for key in SPECIALIST_KEYS:
        label = AGENT_LABELS[key]
        yield _ev(key, "running", f"{label} examining evidence…")
        flags = run_specialist(key, ctx)
        all_flags.extend(flags)
        if flags:
            top = flags[0]
            yield _ev(key, "done", f"{label}: {len(flags)} flag(s) — {top.title}",
                      {"flags": [f.to_dict() for f in flags]})
        else:
            yield _ev(key, "done", f"{label}: no grounded concern.", {"flags": []})

    # ---- collector ----
    yield _ev("collector", "running", "Collecting flags into shared state…")
    # grounding rule: drop any flag with no resolvable evidence_refs
    grounded = [f for f in all_flags if f.evidence_refs]
    dropped = len(all_flags) - len(grounded)
    yield _ev("collector", "done",
              f"{len(grounded)} grounded flag(s)" + (f"; dropped {dropped} unreferenced." if dropped else "."),
              {"flags": [f.to_dict() for f in grounded]})

    # ---- challenger ----
    yield _ev("challenger", "running", "Red-teaming each flag for a benign explanation…")
    rebuttals = run_challenger(grounded, ctx)
    surviving = sum(1 for r in rebuttals if r.residual_concern >= 0.25)
    yield _ev("challenger", "done",
              f"{surviving}/{len(rebuttals)} flag(s) retain material residual concern.",
              {"rebuttals": [r.to_dict() for r in rebuttals]})

    # ---- analogue ----
    yield _ev("analogue", "running", "Matching pattern fingerprint to known cases…")
    analogues = run_analogue(score, ctx["features"])
    if analogues:
        yield _ev("analogue", "done",
                  f"Nearest: {analogues[0].case_name} (sim {analogues[0].similarity:.2f}).",
                  {"analogues": [a.to_dict() for a in analogues]})
    else:
        yield _ev("analogue", "done", "No strong historical analogue.", {"analogues": []})

    # ---- synthesis ----
    yield _ev("synthesis", "running", "Chair composing the ranked dossier memo…")
    memo = run_synthesis(ctx["entity"], ctx["fiscal_year"], ctx.get("accession"),
                         score, grounded, rebuttals, analogues)
    yield _ev("synthesis", "done", "Dossier ready.")

    dossier = Dossier(
        cik=ctx["cik"], accession=ctx.get("accession"), entity=ctx["entity"],
        fiscal_year=ctx["fiscal_year"], point_in_time=ctx.get("point_in_time", ""),
        calibrated_score=score["calibrated_p"], confidence=score["confidence"],
        band=score["band"], contributions=score["contributions"],
        flags=[f.to_dict() for f in grounded],
        rebuttals=[r.to_dict() for r in rebuttals],
        analogues=[a.to_dict() for a in analogues],
        memo=memo, llm_mode=mode,
    )
    yield _ev("__final__", "done", "complete", {"dossier": dossier.to_dict()})


def run_agent_graph(ctx: dict, score: dict) -> dict:
    """Run the full graph and return the dossier dict (consumes the stream)."""
    final = {}
    for ev in stream_agent_graph(ctx, score):
        if ev["node"] == "__final__":
            final = ev["payload"]["dossier"]
    return final
