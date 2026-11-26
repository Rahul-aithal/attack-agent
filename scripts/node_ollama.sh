#!/usr/bin/env bash
# Run on each MODEL machine: bind Ollama to the network and pull that node's models.
# Usage: bash scripts/node_ollama.sh llama3.1:8b qwen2.5:3b
set -e
export OLLAMA_HOST=0.0.0.0
if ! command -v ollama >/dev/null 2>&1; then
    echo "==> Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi
if ! curl -s "http://localhost:11434/api/tags" >/dev/null 2>&1; then
    echo "==> Starting Ollama bound to 0.0.0.0 ..."
    nohup ollama serve >/tmp/ollama.log 2>&1 &
    sleep 3
fi
for model in "$@"; do
    echo "==> Pulling $model"
    ollama pull "$model"
done
echo "==> This node is reachable at http://$(hostname -I 2>/dev/null | awk '{print $1}'):11434"
echo "    (or use its Tailscale 100.x address). Add it to deploy.yaml."
