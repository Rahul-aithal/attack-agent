# Project Plan

Final Year Project. Research prototype for measuring, with consent, how personality signals in
conversation relate to susceptibility in a harmless simulated scenario. All scenarios are
fictional; no credentials, real links, or payment data are ever involved. Every session has a
consent step and a debrief.

Current status (2026-11-07): CLI MVP works end to end; 25 tests pass. Below is the remaining work.

---

> **Status 2026-11-07:** Phases 0–4 implemented (backend, provider/routing, Beta profiler,
> IPIP-50, twin+judge, strategy map, safety filter, async SessionEngine, SQLite storage, FastAPI
> + WebSocket, React/Tailwind web UI, synthetic-persona evaluation + analysis scripts). 43 tests
> pass offline. Phase 5 (write-up) and real-participant data remain, plus the literature citations
> in `config_data/strategy_map.yaml` must be verified before publication.

## Build order

1. Housekeeping
2. Finish the backend
3. HTTP/WebSocket API
4. Web UI (separate app)
5. Simulated-participant evaluation
6. Write-up

The TUI stays as a developer tool. The web UI is the final deliverable.

---

## Deployment across 3 laptops

Models run on whichever machines have the RAM; the backend and UI run on the host and are light.

| Machine | Role | Model size |
|---|---|---|
| 16 GB laptop | Conversation agent + signal extractor | 7–8B, 4-bit |
| 8 GB MacBook | Twin + simulated participants | 3–4B, 4-bit |
| Host (8 GB + RTX 2050) | Backend, web UI, SQLite; optional small judge model | ≤ 4B, 4-bit |

- Each model machine runs Ollama bound to the network (`OLLAMA_HOST=0.0.0.0`). Tailscale is the
  easiest way to give them stable addresses across networks.
- Using a **different model family per role** (agent / twin / judge) avoids a model evaluating its
  own output, which is worth stating in the write-up.
- Single-machine mode: point every role at `localhost`.
- A node registry health-checks each machine and falls back to the next node, then a local small
  model, then an optional cloud key, if one goes offline.

### BYOK (optional)

- One OpenAI-compatible adapter covers Ollama, LM Studio, OpenAI, Groq, OpenRouter. Add Anthropic
  and Gemini adapters.
- Keys are entered in the UI, held in memory per session only, never written to disk or logs, and
  redacted from exports.

---

## Phase 0 — Housekeeping

- [x] `.gitattributes` (`* text=auto eol=lf`) and renormalize (the 32 "modified" files are only
      CRLF line-ending differences).
- [x] Rebuild `.venv` (`rm -rf .venv && uv sync`).
- [x] Add `ruff` and `mypy` to dev dependencies.

## Phase 1 — Backend

### 1.1 Provider / routing layer (`engine/llm/`)
- [x] `Provider` interface: `chat_text`, `chat_json`, `stream`, `health`, `list_models`.
- [x] Adapters: `OllamaProvider`, `OpenAICompatProvider`, `AnthropicProvider`, `GeminiProvider`.
- [x] Role → (node, model) routing with a fallback chain. Roles: `agent`, `extractor`, `twin`,
      `judge`, `sim_participant`.
- [x] Use native JSON/schema output where available; keep the current repair-retry as fallback.
- [x] Log each call (role, model, node, latency, parse success) for a cost/latency table.

### 1.2 Profiler v2
- [x] Replace the hand-tuned update and `1 - exp(-0.35n)` confidence with a **Beta posterior per
      trait**: weighted high/low evidence updates α and β; score = posterior mean; confidence
      falls when evidence is contradictory, not only with count.
- [x] Make the keyword fallback symmetric (detect low signals too).
- [x] Expose all constants in `Settings` for parameter sweeps.
- [x] Output 1–5 trait scores so they compare directly with standard self-report scores.

### 1.3 Self-report questionnaire (ground truth)
- [x] IPIP-50 Big Five markers (public domain), with scoring and reverse-keyed items.
- [x] Given **after** the chat, before the debrief, so it doesn't prime the conversation.
- [x] Stored next to the inferred profile — this is the main accuracy measure.

### 1.4 Twin generator (replaces the manual prediction file)
- [x] Build a persona prompt from the profile (scores, style, evidence quotes).
- [x] Twin produces a predicted outcome + confidence + reasoning; judge-model classifies.
- [x] Keep `twin_prediction.txt` as an optional manual override.

### 1.5 Strategy map with sources
- [x] Move the trait → principle table into `config/strategy_map.yaml` with one citation per row;
      verify each reference before citing.
- [x] Selection modes for experiments: `literature_map`, `twin_driven`, `random`, `fixed:<x>`.

### 1.6 Scenario handling
- [x] Allow up to N configurable scenario exchanges; outcome judged over the whole exchange.
- [x] Post-generation safety filter that rejects any message requesting passwords, OTPs, payment
      details, or real URLs, and regenerates.

### 1.7 Session engine
- [x] Extract the session flow out of `cli/chat.py` into an async `SessionEngine` that emits
      events (`agent_token`, `trait_update`, `phase_change`, `twin_prediction`,
      `scenario_message`, `outcome`, `questionnaire`, `debrief`, `error`).
- [x] Phases: CONSENT → PROFILING → TWIN_HANDOFF → SIMULATION → EVALUATION → QUESTIONNAIRE →
      DEBRIEF → COMPLETE, with pause/resume/abort.
- [x] CLI, API, and batch runner all become thin clients of the engine.

### 1.8 Storage
- [x] SQLite via SQLModel: `participants` (pseudonymous id), `sessions`, `turns`, `evidence`,
      `trait_snapshots`, `predictions`, `outcomes`, `questionnaires`, `llm_calls`.
- [x] JSON/CSV export and a "delete my data" operation.

### 1.9 Tests
- [x] Beta profiler, questionnaire scoring, router fallback, safety filter.
- [x] Full session with a fake provider; abort and node-down paths.

## Phase 2 — API (FastAPI)

- `POST /sessions`, `GET /sessions/{id}`
- `WS /sessions/{id}/stream` — engine events out, participant messages in (token streaming)
- `POST /sessions/{id}/questionnaire`, `/abort`, `GET /sessions/{id}/export`
- `GET /nodes`, `PUT /routing`, `POST /byok`
- `GET/POST /experiments`
- Researcher endpoints behind an admin token; participant endpoints never return trait data (the
  participant must not see their live profile — it would bias the study).
- OpenAPI schema auto-generated; frontend generates a typed client from it.

## Phase 3 — Web UI (`web/`)

Vite + React + TypeScript + Tailwind + shadcn/ui; Recharts for radar/line charts. Pure SPA talking
to FastAPI.

- **Participant view:** consent → streaming chat → scenario message styled as an incoming note →
  questionnaire → debrief.
- **Researcher/presenter view:** live Big Five radar with confidence, per-turn convergence lines,
  ReAct trace, evidence feed, twin prediction vs outcome, node status panel, and settings
  (routing, BYOK, parameters) and an experiments page.
- Demo: participant chats on one device; host projects the presenter view of the same session.

## Phase 4 — Evaluation (simulated participants)

- [x] Synthetic personas with **known** Big Five scores, played by the `sim_participant` role on a
      different model family from the agent.
- [x] Exp 1 — accuracy: Pearson r and MAE per trait vs turn count.
- [x] Exp 2 — ablations: keyword-only vs LLM extractor; model size; stopping rule on/off;
      Beta profiler vs v1.
- [x] Exp 3 — calibration: does high confidence mean low error? (reliability plot)
- [x] Exp 4 — twin prediction: match rate, confusion matrix; selection-mode comparison.
- [x] Judge validation: hand-label ~100 outcomes, report Cohen's κ.
- [x] Optional: public personality-labelled text dataset; small real-participant pilot after
      university ethics approval.
- [x] `analysis/` scripts generate every table and figure from SQLite.

## Phase 5 — Write-up

- Target a workshop / student track first; extend to a conference or journal once real-participant
  data exists.
- Sections: motivation (defensive — measuring susceptibility), related work, method, system,
  experiments, results, ethics, limitations, future work.
