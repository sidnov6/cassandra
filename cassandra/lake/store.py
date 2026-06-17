"""Medallion store: versioned parquet tables with a manifest for Delta-style time-travel.

Layout:
    data/lake/<layer>/<table>/v000001.parquet
    data/lake/<layer>/<table>/_manifest.json   # [{version, path, rows, written_at, note}, ...]

`append` is idempotent on a key set (re-running a crawl never duplicates rows). `read`
returns the latest snapshot unless a `version` is requested. `partition_cols` are recorded
in the manifest (used by callers for `filing_year`/`sic` partitioning semantics).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from ..config import DATA_DIR, ROOT

SEED_DIR = ROOT / "seed"   # committed single-snapshot tables for zero-setup demos (HF Space)

# table -> layer
TABLES = {
    "bronze_filings": "bronze",
    "silver_financials": "silver",
    "silver_text_sections": "silver",
    "silver_graph_edges": "silver",
    "labels_aligned": "silver",
    "gold_firm_filing_features": "gold",
    "sentinel_alerts": "gold",            # autonomous-monitor irregularity alerts
}


class MedallionStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else (DATA_DIR / "lake")
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths / manifest
    def _table_dir(self, table: str) -> Path:
        layer = TABLES.get(table, "bronze")
        d = self.root / layer / table
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _manifest_path(self, table: str) -> Path:
        return self._table_dir(table) / "_manifest.json"

    def _manifest(self, table: str) -> list[dict]:
        p = self._manifest_path(table)
        if p.exists():
            return json.loads(p.read_text())
        return []

    def _write_manifest(self, table: str, manifest: list[dict]) -> None:
        self._manifest_path(table).write_text(json.dumps(manifest, indent=2))

    # ------------------------------------------------------------------ write / append
    def write(self, table: str, df: pd.DataFrame, note: str = "",
              partition_cols: Optional[list[str]] = None, written_at: str = "") -> int:
        """Write a new snapshot version of `table`. Returns the new version number."""
        manifest = self._manifest(table)
        version = (manifest[-1]["version"] + 1) if manifest else 1
        fname = f"v{version:06d}.parquet"
        path = self._table_dir(table) / fname
        df.to_parquet(path, index=False)
        manifest.append({
            "version": version, "path": fname, "rows": int(len(df)),
            "written_at": written_at, "note": note,
            "partition_cols": partition_cols or [], "columns": list(df.columns),
        })
        self._write_manifest(table, manifest)
        return version

    def append(self, table: str, df: pd.DataFrame, key_cols: list[str],
               note: str = "", written_at: str = "") -> int:
        """Idempotent append: union with the latest snapshot, dedupe on `key_cols`, write a
        new version. Re-running an ingest never duplicates rows."""
        if df.empty:
            return self.latest_version(table)
        existing = self.read(table)
        if existing is not None and not existing.empty:
            combined = pd.concat([existing, df], ignore_index=True)
        else:
            combined = df.copy()
        combined = combined.drop_duplicates(subset=key_cols, keep="last").reset_index(drop=True)
        return self.write(table, combined, note=note or "append", written_at=written_at)

    # ------------------------------------------------------------------ read / time-travel
    def latest_version(self, table: str) -> int:
        m = self._manifest(table)
        return m[-1]["version"] if m else 0

    def read(self, table: str, version: Optional[int] = None) -> Optional[pd.DataFrame]:
        manifest = self._manifest(table)
        if not manifest:
            # zero-setup fallback: a committed CSV seed snapshot (text, no Git LFS) so a fresh
            # deploy (e.g. a Hugging Face Space) has demo data out of the box.
            seed = SEED_DIR / f"{table}.csv"
            if seed.exists():
                try:
                    df = pd.read_csv(seed)
                    for c in ("cik", "accession"):           # keep id columns as zero-padded strings
                        if c in df.columns:
                            df[c] = df[c].astype(str).str.split(".").str[0]
                            if c == "cik":
                                df[c] = df[c].str.zfill(10)
                    return df
                except Exception:
                    return None
            return None
        if version is None:
            entry = manifest[-1]
        else:
            entry = next((e for e in manifest if e["version"] == version), None)
            if entry is None:
                raise ValueError(f"{table}: version {version} not found")
        return pd.read_parquet(self._table_dir(table) / entry["path"])

    def history(self, table: str) -> list[dict]:
        return self._manifest(table)

    def tables(self) -> dict[str, dict]:
        out = {}
        for table in TABLES:
            m = self._manifest(table)
            if m:
                out[table] = {"layer": TABLES[table], "versions": len(m),
                              "rows": m[-1]["rows"], "columns": len(m[-1]["columns"])}
        return out
