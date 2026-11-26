#!/usr/bin/env bash
# Run the HTTP/WebSocket API (serves the built web UI if web/dist exists).
set -e
cd "$(dirname "$0")/.."
uv sync
if [ ! -d web/dist ] && command -v npm >/dev/null 2>&1; then
    echo "==> Building web UI..."
    (cd web && npm install && npm run build)
fi
echo "==> Starting API on http://0.0.0.0:${ATTACK_AGENT_API_PORT:-8000}"
echo "    (admin token is printed below; researchers need it)"
uv run attack-agent-serve
