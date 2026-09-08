# Attack Agent — EdgeClone / SE-AgentSim

Autonomous conversational agent that profiles a consenting participant's **Big Five personality traits** through natural conversation (ReAct loop: Observe → Reason → Act), hands the profile to a **Digital Twin Generator**, runs a **controlled, harmless social-engineering scenario**, and compares the twin's predicted outcome with the real outcome (`match_flag`).

> Academic research prototype (Final Year Project). All scenarios are harmless simulations. No credentials, real links, or malware are ever involved.

## Architecture

```
Participant
     │  natural chat (CLI)
     ▼
┌──────────────────────────────┐
│  ATTACK AGENT (this repo)    │
│  ReAct loop                  │
│  ├─ observe: signal extract  │
│  ├─ reason: Big Five + conf  │
│  └─ act: adaptive reply      │
│  profile validator (Ollama)  │
└──────────────┬───────────────┘
               ▼
     outputs/twin_data.txt   ──►  Digital Twin Generator (part 2)
               │                     (writes twin_prediction.txt)
               ▼
     outputs/twin_prediction.txt
               │
               ▼
┌──────────────────────────────┐
│  CONTROLLED SIMULATION       │
│  principle-based scenario    │
│  (authority, social proof,…) │
│  outcome evaluation          │
└──────────────┬───────────────┘
               ▼
  SUCCESS / PARTIAL / FAILURE
  twin prediction vs real outcome → match_flag
               │
               ▼
     outputs/session_log.json
```

## Tech Stack

| Component | Choice |
|---|---|
| Language | Python 3.11+ |
| Packages | `uv` |
| LLM | Ollama + `llama3.2:3b` (free, local) |
| Schemas | Pydantic v2 |
| CLI | `rich` |

## Quick Start

### 1. Install Ollama + model (one-time)

```bash
bash scripts/install_ollama.sh
```

Or manually:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull llama3.2:3b
```

### 2. Run the agent

```bash
uv sync
uv run attack-agent
```

(or `bash scripts/run_agent.sh`)

### 3. Digital Twin handoff (demo mode)

After profiling completes, the agent writes `outputs/twin_data.txt` (Big Five scores, confidences, communication style, evidence log). This is the artifact fed to the Digital Twin Generator.

Until the Digital Twin (part 2) is connected, provide its prediction manually in `outputs/twin_prediction.txt`:

```
PREDICTED_OUTCOME: PARTIAL
PREDICTION_CONFIDENCE: 0.78
PRINCIPLES_USED: ["authority"]
REASONING: high conscientiousness suggests verification behavior under authority pressure
```

The agent waits at a prompt so you can create this file mid-session, or press Enter to use a placeholder.

## Outputs

| File | Content |
|---|---|
| `outputs/twin_data.txt` | Human-readable profile handoff for the Digital Twin |
| `outputs/twin_prediction.txt` | Twin's predicted outcome (manual for now) |
| `outputs/session_log.json` | Full research log: profile, confidences, evidence, turns, strategy, outcome, `match_flag` |
| `outputs/logs/` | Debug logs |

## CLI Commands

- `/status` — show live Big Five profile with confidence
- `/quit` — end session (log still saved)

## Configuration

Environment variables (prefix `ATTACK_AGENT_`), see `.env.example`:

- `ATTACK_AGENT_MODEL_NAME` (default `llama3.2:3b`)
- `ATTACK_AGENT_OLLAMA_HOST` (default `http://localhost:11434`)
- `ATTACK_AGENT_MIN_TURNS` / `ATTACK_AGENT_MAX_TURNS` (8 / 20)
- `ATTACK_AGENT_OUTPUT_DIR` (default `outputs`)

Profiling completion requires: minimum turns, ≥4 traits with sufficient confidence, average confidence above threshold, and profile stability — with a max-turns fallback.

## Ethics

- Explicit consent banner before the session and a debrief after.
- Scenarios are harmless: the simulated task is only "open a simulated portal and confirm your laptop asset ID" — never passwords, OTPs, or real links.
- Session can be aborted anytime; everything stays local.

## Roadmap (Part 2)

- Digital Twin Generator (local persona model from `twin_data.txt`)
- HTTP/MCP integration for twin prediction (replacing the manual file)
- Web UI for participant studies
- Strategy switching on detected resistance
- Batch experiment runner + aggregate trait × principle susceptibility analysis

## Development

```bash
uv sync
uv run pytest
```
