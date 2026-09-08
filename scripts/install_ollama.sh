#!/usr/bin/env bash
set -e

echo "==> Installing Ollama..."
if command -v ollama >/dev/null 2>&1; then
    echo "Ollama already installed."
else
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "==> Starting Ollama server (if not running)..."
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    nohup ollama serve >/dev/null 2>&1 &
    for i in $(seq 1 15); do
        if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
            echo "Ollama server is up."
            break
        fi
        sleep 1
    done
else
    echo "Ollama server already running."
fi

echo "==> Pulling model llama3.2:3b (this may take a few minutes)..."
ollama pull llama3.2:3b

echo ""
echo "==> Done. Verify with:"
echo "    ollama list"
echo ""
echo "==> Then run the Attack Agent:"
echo "    uv sync && uv run attack-agent"
