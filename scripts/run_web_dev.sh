#!/usr/bin/env bash
# Run the web UI in dev mode (Vite) against a local API on :8000. Start the API first with serve.sh.
set -e
cd "$(dirname "$0")/../web"
bun install
bun run dev
