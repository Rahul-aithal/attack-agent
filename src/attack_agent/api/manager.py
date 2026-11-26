"""Process-wide session manager: owns the shared Router, tracks live SessionEngines, records
per-session LLM calls, and persists finished sessions to storage. Also holds the (in-memory)
experiment registry and BYOK nodes."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from attack_agent.config import Settings, get_settings
from attack_agent.engine.llm import LLMCallRecord, Route, Router
from attack_agent.engine.session_engine import SessionEngine
from attack_agent.storage import ensure_participant, persist_session

# Join codes avoid look-alike characters (0/O, 1/I/L) so they can be read out loud.
JOIN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
JOIN_CODE_LENGTH = 6

# Event types that reveal the live inferred profile; withheld from participant-facing streams so
# the participant never sees their own profile mid-study (it would bias their behaviour).
RESEARCHER_ONLY_EVENTS = {"trait_update", "profile", "twin_prediction", "agent_plan", "intervention"}


@dataclass
class Experiment:
    id: str
    name: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    session_ids: list[str] = field(default_factory=list)


class SessionManager:
    def __init__(self, settings: Settings | None = None, router: Router | None = None):
        self.settings = settings or get_settings()
        self.router = router or Router.from_settings(self.settings)
        self.admin_token = self.settings.admin_token or secrets.token_urlsafe(24)
        self.sessions: dict[str, SessionEngine] = {}
        self._calls: dict[str, list[LLMCallRecord]] = {}
        self._meta: dict[str, dict] = {}
        self.experiments: dict[str, Experiment] = {}
        self._persisted: set[str] = set()
        self._watchers: dict[str, asyncio.Task] = {}
        # Researcher dashboard feeds (one queue per open /admin/stream socket).
        self._admin_feeds: set[asyncio.Queue[dict]] = set()
        self._join_codes: dict[str, str] = {}  # code -> session id
        self._participant_sockets: dict[str, int] = {}
        self._participant_ws: dict[str, Any] = {}  # the one socket allowed to drive a session
        self._pending_aborts: dict[str, asyncio.Task] = {}
        self._questionnaire_progress: dict[str, int] = {}
        # Live monitoring for the dashboard: machine telemetry pushed by scripts/node_monitor.py,
        # and every model call (in flight + recent + per-role totals).
        self.machines: dict[str, dict] = {}
        self._active_calls: dict[str, dict] = {}
        self._recent_calls: deque[dict] = deque(maxlen=40)
        self._call_totals: dict[str, dict] = {}
        self.router.on_call_start(self._call_started)
        self.router.on_call(self._record_call)

    # ------------------------------------------------------------------ calls
    def _record_call(self, record: LLMCallRecord) -> None:
        if record.session_id:
            self._calls.setdefault(record.session_id, []).append(record)
        started = self._active_calls.pop(record.call_id or "", None)
        done = {
            **(started or {}),
            **record.to_dict(),
            "join_code": self.join_code(record.session_id) if record.session_id else None,
        }
        self._recent_calls.appendleft(done)
        key = f"{record.role}@{record.node}/{record.model}"
        tot = self._call_totals.setdefault(
            key,
            {"role": record.role, "node": record.node, "model": record.model,
             "calls": 0, "failed": 0, "total_ms": 0.0, "last_ms": 0.0},
        )
        tot["calls"] += 1
        tot["failed"] += 0 if record.ok else 1
        tot["total_ms"] += record.latency_ms
        tot["last_ms"] = record.latency_ms
        self._broadcast(self.llm_snapshot())

    def _call_started(self, info: dict) -> None:
        sid = info.get("session_id")
        self._active_calls[info["call_id"]] = {
            **info,
            "join_code": self.join_code(sid) if sid else None,
            "_t0": time.monotonic(),
        }
        self._broadcast(self.llm_snapshot())

    def llm_snapshot(self) -> dict:
        now = time.monotonic()
        active = [
            {**{k: v for k, v in c.items() if k != "_t0"}, "running_ms": round((now - c["_t0"]) * 1000)}
            for c in self._active_calls.values()
        ]
        totals = [
            {**t, "avg_ms": round(t["total_ms"] / t["calls"], 1) if t["calls"] else 0.0}
            for t in self._call_totals.values()
        ]
        return {
            "type": "llm",
            "active": active,
            "recent": [{k: v for k, v in c.items() if k != "_t0"} for c in self._recent_calls],
            "totals": totals,
        }

    # ------------------------------------------------------------------ machine telemetry
    def update_machine(self, name: str, data: dict) -> None:
        self.machines[name] = {**data, "name": name, "received_at": datetime.now(UTC).isoformat()}
        self._broadcast(self.machines_snapshot())

    def machines_snapshot(self) -> dict:
        return {"type": "machines", "machines": list(self.machines.values())}

    def set_questionnaire_progress(self, session_id: str, answered: int) -> None:
        self._questionnaire_progress[session_id] = max(0, int(answered))
        self._broadcast_sessions()

    # ------------------------------------------------------------------ sessions
    def create_session(
        self,
        participant_id: str | None = None,
        experiment_id: str | None = None,
        config: dict | None = None,
    ) -> SessionEngine:
        engine = SessionEngine(self.router, settings=self.settings)
        sid = engine.session_id
        if participant_id:
            try:
                ensure_participant(participant_id, settings=self.settings)
            except Exception as exc:  # storage is best-effort for a live session
                logger.warning("ensure_participant failed: {}", exc)
        self.sessions[sid] = engine
        code = self._new_join_code()
        self._join_codes[code] = sid
        self._meta[sid] = {
            "join_code": code,
            "participant_id": participant_id,
            "experiment_id": experiment_id,
            "config": config or {},
        }
        if experiment_id and experiment_id in self.experiments:
            self.experiments[experiment_id].session_ids.append(sid)
        # Save the session when it ends, independent of who is connected. The sockets used to
        # do this, so a participant closing the tab (abort) meant the session was never stored.
        self._watchers[sid] = asyncio.create_task(self._persist_when_done(sid, engine))
        self._broadcast_sessions()
        return engine

    def _new_join_code(self) -> str:
        while True:
            code = "".join(secrets.choice(JOIN_ALPHABET) for _ in range(JOIN_CODE_LENGTH))
            if code not in self._join_codes:
                return code

    def join_code(self, session_id: str) -> str | None:
        return self._meta.get(session_id, {}).get("join_code")

    def resolve_join_code(self, code: str) -> str | None:
        return self._join_codes.get(code.strip().upper().replace(" ", "").replace("-", ""))

    # ------------------------------------------------------------------ participant presence
    def claim_participant_socket(self, session_id: str, ws: Any) -> Any | None:
        """Only one participant connection may drive a session. The newest one wins (a rejoin
        after a dropped connection often arrives before the old socket is noticed as dead);
        the previous socket is returned so the caller can tell it and close it."""
        previous = self._participant_ws.get(session_id)
        self._participant_ws[session_id] = ws
        return previous if previous is not ws else None

    def owns_session(self, session_id: str, ws: Any) -> bool:
        return self._participant_ws.get(session_id) is ws

    def release_participant_socket(self, session_id: str, ws: Any) -> None:
        if self._participant_ws.get(session_id) is ws:
            self._participant_ws.pop(session_id, None)

    def participant_connected(self, session_id: str) -> None:
        self._participant_sockets[session_id] = self._participant_sockets.get(session_id, 0) + 1
        pending = self._pending_aborts.pop(session_id, None)
        if pending is not None:
            pending.cancel()
            logger.info("participant rejoined {}", session_id)
        self._broadcast_sessions()

    def participant_disconnected(self, session_id: str) -> None:
        count = max(0, self._participant_sockets.get(session_id, 1) - 1)
        self._participant_sockets[session_id] = count
        self._broadcast_sessions()
        engine = self.sessions.get(session_id)
        if count or engine is None or engine.finished or session_id in self._pending_aborts:
            return
        self._pending_aborts[session_id] = asyncio.create_task(
            self._abort_after_grace(session_id, engine)
        )

    async def _abort_after_grace(self, session_id: str, engine: SessionEngine) -> None:
        grace = self.settings.participant_grace_seconds
        logger.info("participant left {}; aborting in {:.0f}s unless they rejoin", session_id, grace)
        await asyncio.sleep(grace)
        self._pending_aborts.pop(session_id, None)
        if not self._participant_sockets.get(session_id) and not engine.finished:
            logger.info("participant did not return; aborting {}", session_id)
            engine.abort()

    # ------------------------------------------------------------------ researcher feed
    def admin_subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._admin_feeds.add(queue)
        return queue

    def admin_unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._admin_feeds.discard(queue)

    def _broadcast(self, message: dict) -> None:
        for queue in list(self._admin_feeds):
            queue.put_nowait(message)

    def _broadcast_sessions(self) -> None:
        if self._admin_feeds:
            self._broadcast({"type": "sessions", "sessions": self.list_sessions()})

    async def wait_persisted(self, session_id: str) -> None:
        """Block until the finished session has been written (so an export right after works)."""
        task = self._watchers.get(session_id)
        if task is not None:
            await asyncio.shield(task)

    async def _persist_when_done(self, session_id: str, engine: SessionEngine) -> None:
        async for event in engine.events(start=False):
            # phase and turn count are what the researcher's session list shows
            if event.get("type") in ("phase_change", "profile"):
                self._broadcast_sessions()
        self._broadcast_sessions()  # now marked finished
        await self.persist(session_id)

    def get(self, session_id: str) -> SessionEngine | None:
        return self.sessions.get(session_id)

    async def persist(self, session_id: str) -> None:
        engine = self.sessions.get(session_id)
        # Several sockets (participant + researchers) may finish the same session; save it once.
        if engine is None or session_id in self._persisted:
            return
        self._persisted.add(session_id)
        meta = self._meta.get(session_id, {})
        calls = self._calls.get(session_id, [])
        try:
            await asyncio.to_thread(
                persist_session,
                engine.state,
                meta.get("participant_id"),
                meta.get("experiment_id"),
                calls,
                {
                    **self._settings_snapshot(),
                    **(meta.get("config") or {}),
                    "device": engine.state.device,
                    "twin": (
                        {
                            "source": engine.state.twin_prediction.source,
                            "samples": engine.state.twin_prediction.samples,
                        }
                        if engine.state.twin_prediction
                        else None
                    ),
                    "judged_by": (
                        engine.state.outcome_evaluation.judged_by
                        if engine.state.outcome_evaluation
                        else None
                    ),
                    "researcher_steered": bool(engine.state.interventions),
                    "interventions": engine.state.interventions,
                },
                self.settings,
            )
        except Exception as exc:
            logger.warning("persist_session failed for {}: {}", session_id, exc)

    def _settings_snapshot(self) -> dict:
        s = self.settings
        return {
            "selection_mode": s.selection_mode,
            "profiler_version": s.profiler_version,
            "extractor_mode": s.extractor_mode,
            "stopping_rule": s.stopping_rule,
            "min_turns": s.min_turns,
            "max_turns": s.max_turns,
            "scenario_max_exchanges": s.scenario_max_exchanges,
            "routing": {role: [str(r) for r in routes] for role, routes in self.router.roles.items()},
        }

    def session_summary(self, session_id: str, include_profile: bool) -> dict | None:
        engine = self.sessions.get(session_id)
        if engine is None:
            return None
        state = engine.state
        summary = {
            "session_id": session_id,
            "phase": state.phase.value,
            "turn_count": state.turn_count,
            "real_outcome": state.real_outcome.value if state.real_outcome else None,
            "match_flag": state.match_flag,
            "aborted": state.aborted,
        }
        if include_profile:
            summary["profile"] = {
                n: {"score": round(e.score, 3), "confidence": round(e.confidence, 3)}
                for n, e in state.trait_estimates.items()
            }
            summary["stability"] = round(state.profile_stability, 3)
            summary["self_report"] = state.self_report_scores
        return summary

    def list_sessions(self) -> list[dict]:
        """Newest first; researcher-only (no profile data, just enough to pick one)."""
        rows = []
        for sid, engine in self.sessions.items():
            state = engine.state
            participant_msgs = sum(1 for t in state.turn_logs if t.speaker == "participant")
            agent_msgs = sum(1 for t in state.turn_logs if t.speaker == "agent")
            submitted = (state.questionnaire or {}).get("answered")
            rows.append(
                {
                    "session_id": sid,
                    "join_code": self.join_code(sid),
                    "participant_connected": bool(self._participant_sockets.get(sid)),
                    "phase": state.phase.value if engine.started else "waiting",
                    "turn_count": state.turn_count,
                    "participant_messages": participant_msgs,
                    "agent_messages": agent_msgs,
                    "max_turns": self.settings.max_turns,
                    "questionnaire_answered": (
                        submitted
                        if submitted is not None
                        else self._questionnaire_progress.get(sid, 0)
                    ),
                    "questionnaire_submitted": submitted is not None,
                    "questionnaire_total": 50,
                    "interventions": len(state.interventions),
                    "device": state.device,
                    "finished": engine.finished,
                    "participant_id": self._meta.get(sid, {}).get("participant_id"),
                }
            )
        return list(reversed(rows))

    def filter_event(self, event: dict, include_profile: bool) -> dict | None:
        if not include_profile and event.get("type") in RESEARCHER_ONLY_EVENTS:
            return None
        return event

    # ------------------------------------------------------------------ experiments
    def create_experiment(self, name: str, config: dict | None = None) -> Experiment:
        exp = Experiment(id=f"exp_{secrets.token_hex(4)}", name=name, config=config or {})
        self.experiments[exp.id] = exp
        return exp

    # ------------------------------------------------------------------ nodes / routing / byok
    async def nodes_status(self) -> list[dict]:
        return await self.router.status()

    def set_routing(self, role: str, routes: list[str]) -> None:
        self.router.set_route(role, [Route.parse(r) for r in routes])

    def add_byok(self, name: str, kind: str, url: str | None, api_key: str | None) -> None:
        self.router.add_node(name, kind, url, api_key)

    async def aclose(self) -> None:
        for task in [*self._watchers.values(), *self._pending_aborts.values()]:
            task.cancel()
        await self.router.aclose()
