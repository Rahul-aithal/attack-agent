#!/usr/bin/env bash
# Run the developer CLI (one interactive session).
set -e
cd "$(dirname "$0")/.."
uv sync
uv run attack-agent
