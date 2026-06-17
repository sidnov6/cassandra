"""Central configuration. All knobs live here so the rest of the package stays declarative."""
from __future__ import annotations

import os
from pathlib import Path

# --- Identity (SEC fair-access policy requires a descriptive User-Agent) ---------------
# SEC asks every automated client to identify itself with a contact email.
# Set your own before any heavy use:  export CASSANDRA_SEC_UA="MyTool you@example.com"
SEC_USER_AGENT = os.environ.get(
    "CASSANDRA_SEC_UA",
    "CASSANDRA-research contact@example.com",
)

# SEC fair-access: stay <= 10 requests/second. We throttle conservatively.
SEC_RATE_LIMIT_PER_SEC = float(os.environ.get("CASSANDRA_SEC_RPS", "6"))

# --- Paths -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CASSANDRA_DATA_DIR", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
DOSSIER_DIR = DATA_DIR / "dossiers"
for _d in (DATA_DIR, CACHE_DIR, DOSSIER_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- LLM (agent layer) -----------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Latest, most capable model by default; cheap model for routing/aux if desired.
LLM_MODEL = os.environ.get("CASSANDRA_LLM_MODEL", "claude-opus-4-8")
LLM_ENABLED = bool(ANTHROPIC_API_KEY)

# --- Cache freshness -------------------------------------------------------------------
CACHE_TTL_SECONDS = int(os.environ.get("CASSANDRA_CACHE_TTL", str(7 * 24 * 3600)))
