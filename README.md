# Attack Agent — Conversational Profiling & Controlled Susceptibility Simulation

Academic research prototype (Final Year Project). An autonomous conversational agent profiles a
**consenting** participant's **Big Five** personality traits through natural chat (a ReAct loop:
observe → reason → act), hands the profile to a **digital twin** that predicts how the participant
would react to a **harmless simulated social-engineering scenario**, then compares the twin's
prediction with the real outcome. A self-report questionnaire taken afterwards provides ground
truth for measuring profiling accuracy.

> Defensive framing. Every scenario is fictional and harmless: the only task ever asked is to
> "open a simulated portal and confirm a laptop asset ID". **No** passwords, OTPs, payment details,
> or real links are ever involved — a safety filter rejects and regenerates any message that tries.
> Every session has a consent step and a debrief; data stays on the study's own machines.

---

## What's in the box

| Layer | Where | Notes |
|---|---|---|
| Provider/routing layer | `engine/llm/` | Ollama, OpenAI-compatible, Anthropic, Gemini adapters; role→node→model routing with health-checked fallback |
| Beta-posterior profiler | `engine/profiler.py` | confidence rises with evidence, **falls** when evidence contradicts |
| Signal extractor | `engine/signal_extractor.py` | LLM + symmetric keyword fallback |
| Digital twin + judge | `engine/twin.py` | persona model predicts; a different-family judge classifies |
| Strategy map | `config_data/strategy_map.yaml` | trait→principle table with citations; modes: `literature_map`, `twin_driven`, `random`, `fixed:<p>` |
| Scenario simulator | `engine/simulator.py` | multi-exchange, post-generation safety filter |
| Session engine | `engine/session_engine.py` | async, event-emitting; CONSENT→PROFILING→TWIN→SIMULATION→EVALUATION→QUESTIONNAIRE→DEBRIEF |
| IPIP-50 questionnaire | `data/ipip50.py`, `engine/questionnaire.py` | public-domain Big Five markers, scored |
| Storage | `storage/` | SQLModel/SQLite; JSON+CSV export; delete-my-data |
| HTTP/WebSocket API | `api/` | FastAPI; participant + researcher endpoints; BYOK |
| Web UI | `web/` | Vite + React + TS + Tailwind + Recharts |
| Evaluation | `evaluation/` | synthetic personas with known traits |
| Analysis | `analysis/` | accuracy, calibration, twin-match, ablation tables from SQLite |

CLI, API, and the evaluation runner are all thin clients of the same `SessionEngine`.

---

## Quick start (single machine)

```bash
# 1. Model backend
bash scripts/install_ollama.sh          # installs Ollama + pulls llama3.2:3b

# 2a. Developer CLI (one session in the terminal)
bash scripts/run_agent.sh

# 2b. OR the full web app (participant + researcher dashboard)
bash scripts/serve.sh                   # builds web/, starts API on :8000, prints an admin token
# open http://localhost:8000
```

With no `deploy.yaml`, every role uses the single local Ollama (`ATTACK_AGENT_OLLAMA_HOST`,
`ATTACK_AGENT_MODEL_NAME`). Copy `.env.example` to `.env` to change defaults.

---

## Running across three laptops

Models run wherever the RAM is; the backend + UI + SQLite run on the host and are light.

| Machine | Role | Model size |
|---|---|---|
| 16 GB laptop | agent + extractor | 7–8B, 4-bit |
| 8 GB MacBook | twin + sim_participant | 3–4B, 4-bit |
| Host (8 GB + RTX 2050) | backend, web UI, SQLite, judge | ≤4B, 4-bit |

On **each model machine**:

```bash
bash scripts/node_ollama.sh llama3.1:8b      # binds Ollama to 0.0.0.0 and pulls the node's models
```

On the **host**:

```bash
cp deploy.example.yaml deploy.yaml           # edit node URLs (Tailscale 100.x addresses are easiest)
bash scripts/serve.sh
```

Routing lives in `deploy.yaml`: each role lists `node/model` routes in priority order, with a global
`fallback` chain. If a node fails a health check or a call, the next route is used, then the
fallback, then (optionally) a cloud key. Using a **different model family per role** keeps a model
from grading its own output.

### BYOK (optional cloud fallback)

Add `openai` / `anthropic` / `gemini` nodes in `deploy.yaml` with `api_key_env: OPENAI_API_KEY`
(etc.), or add a node live from the researcher UI. Keys are held in memory per process only — never
written to disk or logs, and redacted from exports.

---

## The study flow

1. **Consent** — explicit opt-in before anything runs.
2. **Profiling** — casual chat; each turn updates a Beta posterior per trait. The participant never
   sees their live profile (it would bias them); researchers do.
3. **Twin handoff** — the profile builds a persona; the twin predicts the outcome + confidence.
4. **Simulation** — a principle is chosen (`selection_mode`); the actor sends a harmless, safety-
   filtered message; up to `scenario_max_exchanges` turns.
5. **Evaluation** — real outcome judged; `match_flag` = (twin prediction == real outcome).
6. **Questionnaire** — IPIP-50 self-report (the accuracy ground truth), given *after* the chat.
7. **Debrief** — what the session was, and that it was fictional.

---

## API

`POST /sessions` · `GET /sessions/{id}` · `WS /sessions/{id}/stream` (events out, messages in) ·
`POST /sessions/{id}/questionnaire` · `POST /sessions/{id}/abort` · `GET /sessions/{id}/export` ·
`GET /nodes` · `PUT /routing` · `POST /byok` · `GET|POST /experiments` · `GET /export.csv` ·
`DELETE /sessions/{id}` · `DELETE /participants/{id}` (delete-my-data).

Researcher endpoints require the admin token (`X-Admin-Token` header or `?admin_token=`). Interactive
docs at `/docs`. Participant streams never carry live trait data.

---

## Evaluation & analysis

```bash
# Generate sessions with synthetic personas of known traits (needs model nodes up)
uv run attack-agent-eval --personas all --repeats 3 --experiment accuracy
uv run attack-agent-eval --profiler v1 --experiment ablation_v1      # ablation example

# Tables/figures from SQLite
uv run python -m analysis.accuracy       # Pearson r + MAE per trait vs ground truth
uv run python -m analysis.calibration    # error by confidence bin
uv run python -m analysis.twin_match     # match rate + confusion matrix by selection mode
uv run python -m analysis.ablations --key profiler_version
```

---

## Development

```bash
uv sync
uv run pytest           # 43 tests, fully offline (fake model provider)
uv run ruff check src tests analysis
cd web && bun install && bun run build
```

## Ethics

Consent before, debrief after; harmless fictional scenarios only; a safety filter blocks any request
for real secrets or real URLs; all data local; participants can abort anytime and request deletion.
This is a **defensive** study — measuring susceptibility to improve awareness and training.
