#!/usr/bin/env bash
# Run the HTTP/WebSocket API and the web UI. Safe to run after every `git pull`: it updates
# dependencies, repairs a broken .venv and rebuilds the web UI if it changed.
set -e
cd "$(dirname "$0")/.."
source scripts/_prepare.sh
echo "==> Starting API on http://0.0.0.0:${ATTACK_AGENT_API_PORT:-8000}"
echo "    (admin token is printed below; researchers need it)"
exec uv run --no-sync attack-agent-serve
