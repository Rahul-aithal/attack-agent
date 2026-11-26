# Changelog

What changed in Attack Agent, newest first. Dates are commit dates, and the short hash on each
entry identifies its commit (`git show <hash>`).

## 2026-11-26

### Added

- Provider routing for Ollama, OpenAI-compatible, Anthropic and Gemini models, chosen by role, with
  node fallback and per-call logging (`582b6c2`).
- Beta-posterior profiler, IPIP-50 questionnaire, twin generator and judge, YAML strategy map and a
  scenario safety filter (`582b6c2`).
- Async session engine, SQLite storage with export and delete, FastAPI + WebSocket API and a
  React/Tailwind web UI (`582b6c2`).
- Synthetic-persona evaluation and analysis scripts (`582b6c2`).
- Live researcher dashboard: session list, activity bar, and views that survive tab switching
  (`eade09d`).
- 6-character join codes, automatic reconnect with a 2-minute grace period, and a live admin feed
  over WebSocket (`f9810d0`).
- Per-laptop monitoring (`scripts/node_monitor.py`), logged researcher steering, answer counts and a
  mobile layout (`448448d`).
- Per-session and whole-study reports in Markdown or PDF (`082d9f4`).
- Conversation memory that pairs each question with its answer, a guard that regenerates repeated
  questions, and a fresh example angle per topic (`5cf30c0`).

### Changed

- Web UI tooling moved from npm to bun (`069a16e`).
- New three-laptop layout with one model family per role; Ollama calls disable thinking
  (`dc6a304`).
- The participant chat shows a typing indicator and blocks sending while the agent works
  (`348c189`).
- The simulated request arrives as an ordinary message from a new contact, and message length adapts
  to the participant's device (`082d9f4`).
- Profiling questions are open and situational and avoid sensitive topics (`0bed7a8`).
- The twin samples the participant's reply several times (default 3) and predicts by majority.
  Fallback predictions are labelled, and a session whose twin never ran gets no match/miss
  (`a136e81`).
- Default maximum profiling turns raised from 20 to 30 (`19f20d4`).

### Fixed

- Participant and researcher sockets no longer take each other's events, and closing the dashboard
  no longer aborts the participant's session (`eade09d`).
- Experiment options (profiler, extractor, turn limits) were ignored (`19f20d4`).
- Aborted sessions hung and were never saved; sessions are now saved when they end (`19f20d4`).
- Random selection mode could send a scenario written for a different principle than the one
  recorded (`19f20d4`).
- Conversation history was sent to the model twice per reply (`19f20d4`).
- A judge outage crashed the session (`19f20d4`).
- Failed model calls, invalid questionnaire input and duplicate participant connections are handled
  without ending or corrupting a session (`0bed7a8`).
- One slow health check or a missing model no longer takes a whole node out of routing; skipped
  routes are now recorded (`e612b01`).

### Documentation

- Clarified the PowerShell command in the README (`6f1f397`, manoj7maxi).

## 2026-09-08

### Added

- First MVP: ReAct profiling loop, Big Five confidence engine, twin handoff, controlled simulation,
  CLI chat and initial tests (`425a8d8`).
