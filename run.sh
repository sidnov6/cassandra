#!/usr/bin/env bash
# CASSANDRA — one-command launch for the analyst workstation.
#   ./run.sh                 # serve the UI + API at http://127.0.0.1:8000
#   ./run.sh --port 8080
set -euo pipefail
cd "$(dirname "$0")"

PORT=8011   # 8000 is commonly occupied; CASSANDRA defaults to 8011
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    *) shift;;
  esac
done

echo "CASSANDRA API + built-in UI → http://127.0.0.1:${PORT}"
echo "  (agent layer: ${ANTHROPIC_API_KEY:+LLM mode}${ANTHROPIC_API_KEY:-deterministic mode — set ANTHROPIC_API_KEY to enable the LLM path})"
echo "  (for the full Next.js workstation: cd frontend && npm run dev → http://127.0.0.1:3000)"
exec env PYTHONPATH="$(pwd)" python3 -m uvicorn cassandra.api.server:app --host 127.0.0.1 --port "${PORT}"
