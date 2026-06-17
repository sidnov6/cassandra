"""Local medallion lake (blueprint §5.1).

A dependency-light stand-in for Databricks + Delta Lake: parquet files under
bronze/silver/gold, with a per-table JSON manifest that versions every write so we get
Delta-style *time travel* (read any prior snapshot). The point-in-time reconstruction the
project depends on is therefore reproducible from `(table, version)`.
"""
from .store import MedallionStore, TABLES

__all__ = ["MedallionStore", "TABLES"]
