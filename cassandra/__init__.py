"""CASSANDRA — Accounting-Manipulation Detection System (thin-slice reference implementation).

A point-in-time forensic intelligence engine. This package implements Phase-0 of the
architecture blueprint end to end:

    ingest (real SEC EDGAR)  ->  forensic features  ->  fusion scorer
        ->  agentic reasoning (deterministic, LLM-optional)  ->  evidence dossier

Design invariants carried from the blueprint:
  * Point-in-time hygiene: features are built from facts as originally filed, not restated.
  * Graceful degradation: a missing modality (text, LLM) degrades the output, never breaks it.
  * Grounding: every agent flag carries evidence references; unreferenced claims are dropped.
  * Intellectual honesty: the scorer is transparent and every number is traceable to a source.
"""

__version__ = "0.1.0-thinslice"
