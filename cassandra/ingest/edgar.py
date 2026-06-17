"""SEC EDGAR client.

Talks to the free, public SEC endpoints:
  * https://www.sec.gov/files/company_tickers.json        (ticker / name -> CIK)
  * https://data.sec.gov/submissions/CIK##########.json    (filing history)
  * https://data.sec.gov/api/xbrl/companyfacts/CIK#####.json (all XBRL numeric facts)
  * https://www.sec.gov/Archives/edgar/data/...            (raw filing documents)

Respects SEC fair-access: descriptive User-Agent + conservative client-side throttle,
with idempotent on-disk caching keyed by URL so re-runs are cheap and re-playable.

Point-in-time note (blueprint §3.2 / §7): companyfacts returns the *latest* (possibly
restated) view of each fact. We attach the provenance of every fact (accession, form,
filing date) so downstream code can reconstruct an as-originally-filed snapshot and
exclude amendments (10-K/A). See ingest.xbrl.build_panel.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

import requests

from ..config import CACHE_DIR, CACHE_TTL_SECONDS, SEC_RATE_LIMIT_PER_SEC, SEC_USER_AGENT


# --------------------------------------------------------------------------- rate limiting
class _RateLimiter:
    """Minimal thread-safe token-bucket: never exceed `rps` requests/second."""

    def __init__(self, rps: float):
        self._min_interval = 1.0 / max(rps, 0.1)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


@dataclasses.dataclass
class CompanyRef:
    cik: str          # 10-digit zero-padded
    ticker: str
    title: str

    @property
    def cik_int(self) -> int:
        return int(self.cik)


class EdgarClient:
    """Cached, throttled SEC EDGAR client."""

    SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
    COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    TICKERS = "https://www.sec.gov/files/company_tickers.json"
    ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodash}/{doc}"

    def __init__(self, cache_dir: Path = CACHE_DIR, ttl: int = CACHE_TTL_SECONDS):
        self.cache_dir = cache_dir
        self.ttl = ttl
        self._limiter = _RateLimiter(SEC_RATE_LIMIT_PER_SEC)
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
        )
        self._tickers_cache: Optional[list[CompanyRef]] = None

    # ------------------------------------------------------------------ low-level fetch
    def _cache_path(self, url: str, binary: bool = False) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        ext = ".bin" if binary else ".json"
        # Keep text docs as .txt for readability when not json
        if not binary and not url.endswith(".json"):
            ext = ".txt"
        return self.cache_dir / f"{h}{ext}"

    def _get(self, url: str, *, as_json: bool = True) -> Any:
        cp = self._cache_path(url, binary=False)
        if cp.exists() and (time.time() - cp.stat().st_mtime) < self.ttl:
            raw = cp.read_text(encoding="utf-8", errors="replace")
            return json.loads(raw) if as_json else raw

        self._limiter.wait()
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        text = resp.text
        cp.write_text(text, encoding="utf-8")
        return resp.json() if as_json else text

    # ------------------------------------------------------------------ company resolve
    def _load_tickers(self) -> list[CompanyRef]:
        if self._tickers_cache is None:
            data = self._get(self.TICKERS)
            refs = []
            for row in data.values():
                refs.append(
                    CompanyRef(
                        cik=str(row["cik_str"]).zfill(10),
                        ticker=str(row.get("ticker", "")).upper(),
                        title=str(row.get("title", "")),
                    )
                )
            self._tickers_cache = refs
        return self._tickers_cache

    # ------------------------------------------------------------------ full-registrant resolve
    EDGAR_COMPANY = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={q}"
                     "&type=10-K&dateb=&owner=include&count={n}&output=atom")

    def _browse_company(self, query: str, n: int = 10) -> list[CompanyRef]:
        """Resolve ANY SEC registrant by name via EDGAR company search (covers the full
        ~800k-CIK universe, not just ticker-listed firms). Single, close matches return a
        clean conformed-name; broad matches return CIKs (names filled lazily on demand)."""
        import re
        from urllib.parse import quote
        try:
            xml = self._get(self.EDGAR_COMPANY.format(q=quote(query), n=n), as_json=False)
        except Exception:
            return []
        out: list[CompanyRef] = []
        # exact/close single match carries <conformed-name>
        m = re.search(r"<cik>(\d+)</cik>.*?<conformed-name>([^<]+)</conformed-name>", xml, re.S)
        if m:
            out.append(CompanyRef(cik=m.group(1).zfill(10), ticker="", title=m.group(2).strip()))
        # broad matches: collect CIKs (legacy atom mangles names, so resolve via submissions)
        for cik in dict.fromkeys(re.findall(r"<cik>(\d+)</cik>", xml)):
            cik = cik.zfill(10)
            if any(r.cik == cik for r in out):
                continue
            out.append(CompanyRef(cik=cik, ticker="", title=""))
            if len(out) >= n:
                break
        return out

    def resolve(self, query: str) -> Optional[CompanyRef]:
        """Resolve a ticker, CIK, or company name to a CompanyRef — ANY SEC registrant."""
        q = query.strip()
        if not q:
            return None
        # Direct CIK (numeric or "CIK0001234" forms)
        digits = "".join(ch for ch in q if ch.isdigit())
        if q.isdigit() or (q.upper().startswith("CIK") and digits):
            cik = digits.zfill(10)
            try:
                subs = self.submissions(cik)
                return CompanyRef(cik=cik, ticker=(subs.get("tickers") or [""])[0],
                                  title=subs.get("name", ""))
            except Exception:
                return None
        refs = self._load_tickers()
        qu = q.upper()
        for r in refs:                       # exact ticker
            if r.ticker == qu:
                return r
        for r in refs:                       # exact title
            if r.title.upper() == qu:
                return r
        hits = [r for r in refs if qu in r.title.upper()]
        if hits:
            return hits[0]
        # not a listed/ticker firm — resolve against the full EDGAR registrant universe
        for ref in self._browse_company(q, n=5):
            if ref.title:
                return ref
            try:                              # fill the name from submissions
                subs = self.submissions(ref.cik)
                if subs.get("name"):
                    return CompanyRef(cik=ref.cik, ticker=(subs.get("tickers") or [""])[0],
                                      title=subs["name"])
            except Exception:
                continue
        return None

    def search(self, query: str, limit: int = 10) -> list[CompanyRef]:
        """Autocomplete over the ticker universe, then top up with full-registrant matches."""
        refs = self._load_tickers()
        qu = query.strip().upper()
        if not qu:
            return refs[:limit]
        scored: list[tuple[int, CompanyRef]] = []
        for r in refs:
            score = 0
            if r.ticker == qu:
                score = 100
            elif r.ticker.startswith(qu):
                score = 80
            elif qu in r.title.upper():
                score = 60 if r.title.upper().startswith(qu) else 40
            if score:
                scored.append((score, r))
        scored.sort(key=lambda t: (-t[0], t[1].title))
        results = [r for _, r in scored[:limit]]
        # If the ticker universe is thin on this query, surface a full-registrant match too
        # (covers non-ticker filers, foreign private issuers, recent registrants).
        if len(results) < 3 and len(qu) >= 3:
            have = {r.cik for r in results}
            for ref in self._browse_company(query, n=3):
                if ref.cik in have:
                    continue
                if not ref.title:
                    try:
                        subs = self.submissions(ref.cik)
                        ref = CompanyRef(cik=ref.cik, ticker=(subs.get("tickers") or [""])[0],
                                         title=subs.get("name", ""))
                    except Exception:
                        continue
                if ref.title:
                    results.append(ref)
                if len(results) >= limit:
                    break
        return results

    # ------------------------------------------------------------------ filings / facts
    def submissions(self, cik: str) -> dict:
        return self._get(self.SUBMISSIONS.format(cik=cik.zfill(10)))

    def company_facts(self, cik: str) -> dict:
        return self._get(self.COMPANYFACTS.format(cik=cik.zfill(10)))

    def recent_filings(self, cik: str, forms: tuple[str, ...] = ("10-K",),
                       limit: int = 20) -> list[dict]:
        """Return recent filings of the requested form types, newest first.

        Each item: {accession, form, filing_date, period_of_report, primary_doc, is_amendment}.
        """
        subs = self.submissions(cik)
        recent = subs.get("filings", {}).get("recent", {})
        out: list[dict] = []
        n = len(recent.get("accessionNumber", []))
        want = set(forms)
        # also allow amendments of requested forms (e.g. 10-K/A) but flag them
        for i in range(n):
            form = recent["form"][i]
            base = form.split("/")[0]
            if form in want or base in want:
                out.append({
                    "accession": recent["accessionNumber"][i],
                    "form": form,
                    "filing_date": recent["filingDate"][i],
                    "period_of_report": recent.get("reportDate", [None] * n)[i],
                    "primary_doc": recent.get("primaryDocument", [None] * n)[i],
                    "primary_desc": recent.get("primaryDocDescription", [None] * n)[i],
                    "is_amendment": "/A" in form,
                })
            if len(out) >= limit:
                break
        return out

    def filing_document_url(self, cik: str, accession: str, primary_doc: str) -> str:
        accn_nodash = accession.replace("-", "")
        return self.ARCHIVE.format(cik_int=int(cik), accn_nodash=accn_nodash, doc=primary_doc)

    def filing_text(self, cik: str, accession: str, primary_doc: str) -> str:
        """Fetch raw primary-document HTML/text for a filing."""
        url = self.filing_document_url(cik, accession, primary_doc)
        return self._get(url, as_json=False)
