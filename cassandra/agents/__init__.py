"""Layer 4 — Agentic reasoning. Parallel specialists -> challenger -> analogue -> synthesis."""
from .orchestrator import run_agent_graph, stream_agent_graph
from .schema import Flag, Rebuttal, Analogue, Dossier

__all__ = ["run_agent_graph", "stream_agent_graph", "Flag", "Rebuttal", "Analogue", "Dossier"]
