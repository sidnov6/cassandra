"""Layer 1 — Ingestion. Real SEC EDGAR access with point-in-time discipline."""
from .edgar import EdgarClient, CompanyRef
from .xbrl import FinancialsPanel, build_panel

__all__ = ["EdgarClient", "CompanyRef", "FinancialsPanel", "build_panel"]
