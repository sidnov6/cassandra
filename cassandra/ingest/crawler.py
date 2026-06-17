"""EDGAR daily-index crawler (blueprint §5.1).

Pulls the SEC daily full-text index, dedupes by accession number, and lands raw filing
metadata in the bronze layer. Idempotent: re-running the same day never duplicates rows
(the medallion `append` dedupes on accession). This is the firehose entry point; for model
building we also ingest targeted companies via `ingest.edgar` (cheaper than the full stream).
"""
from __future__ import annotations

import io
from datetime import date
from typing import Optional

import pandas as pd

from ..config import SEC_USER_AGENT
from .edgar import EdgarClient


def crawl_daily_index(d: date, client: Optional[EdgarClient] = None,
                      forms: tuple[str, ...] = ("10-K", "10-Q", "8-K")) -> pd.DataFrame:
    """Return the EDGAR daily index for date `d` as a dataframe of filing metadata.

    Columns: cik, company, form_type, filing_date, accession, raw_url.
    """
    client = client or EdgarClient()
    q = d.month  # quarter
    quarter = (d.month - 1) // 3 + 1
    url = (f"https://www.sec.gov/Archives/edgar/daily-index/{d.year}/QTR{quarter}/"
           f"form.{d.strftime('%Y%m%d')}.idx")
    try:
        text = client._get(url, as_json=False)
    except Exception:
        return pd.DataFrame(columns=["cik", "company", "form_type", "filing_date",
                                     "accession", "raw_url"])
    rows = []
    started = False
    for line in text.splitlines():
        if line.startswith("---"):
            started = True
            continue
        if not started or not line.strip():
            continue
        # fixed-width-ish: Form Type, Company Name, CIK, Date Filed, File Name
        parts = [p for p in line.split("  ") if p.strip()]
        if len(parts) < 5:
            continue
        form_type = parts[0].strip()
        if forms and not any(form_type == f or form_type.startswith(f) for f in forms):
            continue
        company = parts[1].strip()
        cik = parts[2].strip().zfill(10)
        filed = parts[3].strip()
        fname = parts[-1].strip()
        accession = fname.split("/")[-1].replace(".txt", "")
        rows.append({"cik": cik, "company": company, "form_type": form_type,
                     "filing_date": filed, "accession": accession,
                     "raw_url": f"https://www.sec.gov/Archives/{fname}"})
    return pd.DataFrame(rows)
