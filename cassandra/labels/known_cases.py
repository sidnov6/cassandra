"""Curated label set of U.S.-filer accounting-manipulation cases.

Seed set (high-confidence public enforcement / restatement matters). A researched, expanded
set can be merged from `data/labels/verified_cases.json` if present (same schema). All are
public record: SEC AAERs, litigation releases, 8-K 4.02 restatements, DOJ/SEC actions.

`fraud_start`/`fraud_end` are the COMMISSION-period years; `enforcement_year` is when it
became public. `sec_xbrl=True` marks U.S. domestic XBRL-era filers usable by the trained
scorer; pre-XBRL and foreign filers are case studies / out-of-distribution.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR


@dataclasses.dataclass
class CaseLabel:
    name: str
    ticker: str
    cik: str
    fraud_start: int
    fraud_end: int
    enforcement_year: int
    mechanism: str
    source: str
    standard: str
    sec_xbrl: bool
    label_strength: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# seed: (name, ticker, fraud_start, fraud_end, enforcement_year, mechanism, source, standard, sec_xbrl, strength)
_SEED = [
    ("Under Armour, Inc.", "UAA", 2015, 2016, 2021, "revenue pull-forward to meet guidance", "SEC enforcement", "US GAAP", True, "gold"),
    ("Hertz Global Holdings", "HTZ", 2011, 2013, 2014, "improper estimates / multi-year restatement", "8-K 4.02 / SEC", "US GAAP", True, "silver"),
    ("Kraft Heinz Co", "KHC", 2015, 2018, 2021, "improper procurement cost accounting", "SEC AAER", "US GAAP", True, "gold"),
    ("General Electric Co", "GE", 2015, 2017, 2020, "insurance reserves & Power-segment margins", "SEC enforcement", "US GAAP", True, "gold"),
    ("MiMedx Group", "MDXG", 2013, 2017, 2019, "channel-stuffing / premature revenue", "SEC AAER", "US GAAP", True, "gold"),
    ("comScore, Inc.", "SCOR", 2014, 2015, 2019, "nonmonetary round-trip revenue inflation", "SEC AAER", "US GAAP", True, "gold"),
    ("Hain Celestial Group", "HAIN", 2014, 2016, 2017, "revenue recognition / concessions to distributors", "8-K 4.02", "US GAAP", True, "silver"),
    ("Synchronoss Technologies", "SNCR", 2015, 2017, 2019, "improper revenue recognition", "SEC AAER", "US GAAP", True, "gold"),
    ("Celadon Group", "CGI", 2014, 2016, 2019, "equipment-trading fraud to hide losses", "DOJ + SEC", "US GAAP", True, "gold"),
    ("Osiris Therapeutics", "OSIR", 2014, 2015, 2017, "fictitious / premature revenue", "SEC AAER", "US GAAP", True, "gold"),
    ("SAExploration Holdings", "SAEX", 2015, 2019, 2020, "fictitious revenue via undisclosed related party", "SEC AAER", "US GAAP", True, "gold"),
    ("Roadrunner Transportation", "RRTS", 2014, 2016, 2017, "multiple-year restatement / understated expenses", "8-K 4.02 / SEC", "US GAAP", True, "silver"),
    ("Marvell Technology Group", "MRVL", 2014, 2015, 2015, "pulling in revenue from future quarters", "SEC enforcement", "US GAAP", True, "gold"),
    ("Weatherford International", "WFT", 2007, 2012, 2016, "improper income-tax accounting", "SEC AAER", "US GAAP", True, "gold"),
    ("Computer Sciences Corp", "CSC", 2009, 2012, 2015, "percentage-of-completion accounting manipulation", "SEC AAER", "US GAAP", True, "gold"),
    ("Logitech International", "LOGI", 2011, 2013, 2016, "improper warranty accrual & inventory valuation", "SEC AAER", "US GAAP", True, "gold"),
    ("Bankrate, Inc.", "RATE", 2012, 2012, 2015, "improper accruals to hit targets ('cookie jar')", "SEC AAER", "US GAAP", True, "gold"),
    ("Bausch Health (Valeant)", "BHC", 2014, 2015, 2020, "Philidor specialty-pharmacy channel revenue", "SEC enforcement", "US GAAP", True, "gold"),
    ("Wells Fargo & Co", "WFC", 2014, 2016, 2020, "cross-sell sales-practice misstatements", "SEC enforcement", "US GAAP", True, "silver"),
    ("Nikola Corp", "NKLA", 2020, 2020, 2021, "misleading statements to investors", "SEC enforcement", "US GAAP", True, "silver"),
    ("Tupperware Brands", "TUP", 2020, 2021, 2023, "material weakness / restatement", "8-K 4.02", "US GAAP", True, "silver"),
    ("Diebold Nixdorf", "DBD", 2008, 2010, 2010, "improper revenue recognition (bill-and-hold)", "SEC AAER", "US GAAP", True, "gold"),
    # --- foreign / pre-XBRL: case studies, out-of-distribution for the trained scorer ---
    ("Luckin Coffee", "LK", 2019, 2019, 2020, "fabricated retail sales / vouchers", "SEC enforcement (20-F)", "US GAAP (20-F)", False, "gold"),
    ("Enron Corp", "ENE", 1997, 2001, 2001, "special-purpose entities / mark-to-model", "SEC / DOJ", "US GAAP", False, "gold"),
    ("WorldCom", "WCOM", 1999, 2001, 2002, "capitalized line-cost operating expenses", "SEC / DOJ", "US GAAP", False, "gold"),
    ("HealthSouth", "HRC", 1996, 2002, 2003, "fabricated earnings to meet analyst targets", "SEC / DOJ", "US GAAP", False, "gold"),
    ("Wirecard AG", "WDI", 2015, 2020, 2020, "fictitious third-party-acquirer cash", "BaFin / insolvency", "IFRS", False, "gold"),
    ("Steinhoff International", "SNH", 2014, 2017, 2019, "fictitious related-party transactions", "PwC investigation", "IFRS", False, "gold"),
]

KNOWN_CASES: list[CaseLabel] = [
    CaseLabel(name=n, ticker=t, cik="", fraud_start=fs, fraud_end=fe, enforcement_year=ey,
              mechanism=mech, source=src, standard=std, sec_xbrl=xbrl, label_strength=strength)
    for (n, t, fs, fe, ey, mech, src, std, xbrl, strength) in _SEED
]


def load_cases(merge_verified: bool = True) -> list[CaseLabel]:
    """Return the seed cases, optionally merged with a researched verified set on disk."""
    cases = {c.ticker or c.name: c for c in KNOWN_CASES}
    vpath = DATA_DIR / "labels" / "verified_cases.json"
    if merge_verified and vpath.exists():
        try:
            data = json.loads(vpath.read_text())
            for d in data:
                if not isinstance(d, dict) or "name" not in d:
                    continue
                c = CaseLabel(
                    name=d["name"], ticker=d.get("ticker", ""), cik=str(d.get("cik", "") or ""),
                    fraud_start=int(d.get("fraud_start_year") or d.get("fraud_start") or 0),
                    fraud_end=int(d.get("fraud_end_year") or d.get("fraud_end") or 0),
                    enforcement_year=int(d.get("enforcement_year") or 0),
                    mechanism=d.get("mechanism", ""), source=d.get("source", ""),
                    standard=d.get("standard", "US GAAP"),
                    sec_xbrl=bool(d.get("sec_xbrl", False)),
                    label_strength=d.get("label_strength", "silver"),
                )
                if c.fraud_start:
                    cases[c.ticker or c.name] = c
        except Exception:
            pass
    return list(cases.values())
