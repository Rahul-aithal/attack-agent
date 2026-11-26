#!/usr/bin/env bash
# Shared setup for the start scripts: install/update dependencies and make sure the code that
# runs is the code in src/ (no stale or broken .venv, no forgotten web build).
# Sourced by serve.sh and run_agent.sh from the repo root.

uv sync -q

# macOS: newer Pythons skip .pth files carrying the "hidden" flag. If the flag ever lands on the
# venv (iCloud-synced folders, some copy tools), the editable install silently stops working;
# clear it every time.
if [ "$(uname)" = "Darwin" ]; then
    chflags -R nohidden .venv 2>/dev/null || true
fi

# Always import the live source tree first, whatever state the .venv is in.
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

# Self-check; repair the environment automatically instead of failing.
if ! uv run --no-sync python -c "import attack_agent.server, attack_agent.reports" >/dev/null 2>&1; then
    echo "==> Python environment looks broken; rebuilding .venv (one-time)..."
    rm -rf .venv
    uv sync -q
    uv run --no-sync python -c "import attack_agent.server" || {
        echo "!! still failing: run 'uv run python -c \"import attack_agent.server\"' to see the error"
        exit 1
    }
fi

# Rebuild the web UI whenever its sources changed since the last build (e.g. after git pull).
if [ -d web ]; then
    stale=0
    if [ ! -f web/dist/index.html ]; then
        stale=1
    elif [ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html 2>/dev/null | head -1)" ]; then
        stale=1
    fi
    if [ "$stale" = 1 ]; then
        if command -v bun >/dev/null 2>&1; then
            echo "==> Web UI changed; rebuilding..."
            (cd web && bun install --silent && bun run build >/dev/null) && echo "    done"
        else
            echo "!! web UI needs a rebuild but bun is not installed (curl -fsSL https://bun.sh/install | bash)"
        fi
    fi
fi
