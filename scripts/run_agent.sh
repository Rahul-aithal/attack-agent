#!/usr/bin/env bash
# Run the developer CLI (one interactive session).
set -e
cd "$(dirname "$0")/.."
source scripts/_prepare.sh
exec uv run --no-sync attack-agent
