"""Process-wide session manager: owns the shared Router, tracks live SessionEngines, records
per-session LLM calls, and persists finished sessions to storage. Also holds the (in-memory)
experiment registry and BYOK nodes."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from attack_agent.config import Settings, get_settings
from attack_agent.engine.llm import LLMCallRecord, Route, Router
from attack_agent.engine.session_engine import SessionEngine
from attack_agent.storage import ensure_participant, persist_session

# Event types that reveal the live inferred profile; withheld from participant-facing streams so
# the participant never sees their own profile mid-study (it would bias their behaviour).
RESEARCHER_ONLY_EVENTS = {"trait_update", "profile", "twin_prediction"}


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
        self.router.on_call(self._record_call)

    # ------------------------------------------------------------------ calls
    def _record_call(self, record: LLMCallRecord) -> None:
        if record.session_id:
            self._calls.setdefault(record.session_id, []).append(record)

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
        self._meta[sid] = {
            "participant_id": participant_id,
            "experiment_id": experiment_id,
            "config": config or {},
        }
        if experiment_id and experiment_id in self.experiments:
            self.experiments[experiment_id].session_ids.append(sid)
        return engine

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
                meta.get("config"),
                self.settings,
            )
        except Exception as exc:
            logger.warning("persist_session failed for {}: {}", session_id, exc)

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
            rows.append(
                {
                    "session_id": sid,
                    "phase": state.phase.value,
                    "turn_count": state.turn_count,
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
        await self.router.aclose()
