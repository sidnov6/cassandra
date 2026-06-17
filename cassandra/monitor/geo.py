"""Map a filer's SEC business address to coordinates for the watchdog map.

EDGAR submissions give a 2-letter business `stateOrCountry`. We place each filer at its
state centroid with a deterministic per-CIK jitter, so many filers in one state spread into
a believable cluster rather than stacking on a single point. (City-level geocoding is the
production upgrade; state-centroid is plenty for the live sweep.)
"""
from __future__ import annotations

import hashlib
from typing import Optional

# (lat, lng) approximate centroids
US_STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AL": (32.8, -86.8), "AK": (64.0, -152.0), "AZ": (34.3, -111.7), "AR": (34.9, -92.4),
    "CA": (37.2, -119.4), "CO": (39.0, -105.5), "CT": (41.6, -72.7), "DE": (39.0, -75.5),
    "DC": (38.9, -77.0), "FL": (28.6, -82.4), "GA": (32.6, -83.4), "HI": (20.3, -156.4),
    "ID": (44.1, -114.1), "IL": (40.0, -89.2), "IN": (39.9, -86.3), "IA": (42.0, -93.5),
    "KS": (38.5, -98.4), "KY": (37.5, -85.3), "LA": (31.0, -92.0), "ME": (45.4, -69.2),
    "MD": (39.0, -76.8), "MA": (42.3, -71.8), "MI": (44.3, -85.4), "MN": (46.3, -94.3),
    "MS": (32.7, -89.7), "MO": (38.4, -92.5), "MT": (47.0, -109.6), "NE": (41.5, -99.8),
    "NV": (39.3, -116.6), "NH": (43.7, -71.6), "NJ": (40.2, -74.7), "NM": (34.4, -106.1),
    "NY": (42.9, -75.5), "NC": (35.5, -79.4), "ND": (47.5, -100.5), "OH": (40.3, -82.8),
    "OK": (35.6, -97.5), "OR": (44.0, -120.6), "PA": (40.9, -77.8), "RI": (41.7, -71.5),
    "SC": (33.9, -80.9), "SD": (44.4, -100.2), "TN": (35.9, -86.4), "TX": (31.5, -99.3),
    "UT": (39.3, -111.7), "VT": (44.1, -72.7), "VA": (37.5, -78.9), "WA": (47.4, -120.5),
    "WV": (38.6, -80.6), "WI": (44.6, -89.9), "WY": (43.0, -107.6), "PR": (18.2, -66.4),
}


def locate(state: Optional[str], cik: str) -> Optional[dict]:
    """Return {'lat','lng','state','onshore'} for a US filer, or None if not US-mappable."""
    if not state:
        return None
    state = state.upper()
    c = US_STATE_CENTROIDS.get(state)
    if c is None:
        # foreign / non-state registrant — not placed on the US map
        return None
    h = int(hashlib.md5(cik.encode()).hexdigest(), 16)
    jlat = ((h % 1000) / 1000 - 0.5) * 2.0
    jlng = (((h // 1000) % 1000) / 1000 - 0.5) * 2.4
    return {"lat": round(c[0] + jlat, 4), "lng": round(c[1] + jlng, 4),
            "state": state, "onshore": True}
