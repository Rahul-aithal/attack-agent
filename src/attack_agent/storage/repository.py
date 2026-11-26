"""Persistence: write a finished (or aborted) session's state into SQLite, plus exports and a
"delete my data" operation. Uses SQLModel/SQLAlchemy synchronously inside a thread-friendly
engine; callers in async code should wrap ``persist_session`` with ``asyncio.to_thread``.
"""

from __future__ import annotations

import csv
import io
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError
from sqlmodel import Session as DBSession
from sqlmodel import SQLModel, create_engine, select

from attack_agent.config import Settings, get_settings
from attack_agent.state import AgentState
from attack_agent.storage.checkpoints import delete_checkpoint
from attack_agent.storage.models import (
    Evidence,
    LLMCall,
    OutcomeRow,
    Participant,
    Prediction,
    Questionnaire,
    Session,
    TraitSnapshot,
    Turn,
)

_engines: dict[str, object] = {}
_engine_lock = threading.Lock()


def get_engine(settings: Settings | None = None):
    settings = settings or get_settings()
    url = settings.database_url
    with _engine_lock:
        if url not in _engines:
            if url.startswith("sqlite:///"):
                db_path = url.replace("sqlite:///", "", 1)
                if db_path and db_path != ":memory:":
                    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(url, connect_args={"check_same_thread": False})
            try:
                SQLModel.metadata.create_all(engine)
            except OperationalError:
                pass  # tables already exist (concurrent creation)
            _engines[url] = engine
        return _engines[url]


def ensure_participant(
    participant_id: str,
    label: str = "",
    is_synthetic: bool = False,
    known_traits: dict[str, float] | None = None,
    settings: Settings | None = None,
) -> str:
    engine = get_engine(settings)
    with DBSession(engine) as db:
        existing = db.get(Participant, participant_id)
        if existing is None:
            db.add(
                Participant(
                    id=participant_id,
                    label=label,
                    is_synthetic=is_synthetic,
                    known_traits=known_traits,
                )
            )
            db.commit()
    return participant_id


def persist_session(
    state: AgentState,
    participant_id: str | None = None,
    experiment_id: str | None = None,
    llm_calls: list | None = None,
    config_snapshot: dict | None = None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    engine = get_engine(settings)
    with DBSession(engine) as db:
        # replace any prior rows for this session id (idempotent re-persist)
        _purge_session(db, state.session_id)

        pred = state.twin_prediction
        ev = state.outcome_evaluation
        db.add(
            Session(
                id=state.session_id,
                participant_id=participant_id,
                experiment_id=experiment_id,
                started_at=state.started_at,
                ended_at=datetime.now(UTC),
                phase=state.phase.value,
                turn_count=state.turn_count,
                completion_reason=state.completion_reason,
                profile_stability=round(state.profile_stability, 4),
                selection_mode=settings.selection_mode,
                principle=state.current_principle.value if state.current_principle else None,
                real_outcome=state.real_outcome.value if state.real_outcome else None,
                twin_outcome=pred.predicted_outcome.value if pred else None,
                match_flag=state.match_flag,
                aborted=state.aborted,
                inferred_profile={n: round(e.score, 4) for n, e in state.trait_estimates.items()},
                inferred_confidence={
                    n: round(e.confidence, 4) for n, e in state.trait_estimates.items()
                },
                self_report_profile=state.self_report_scores,
                config_snapshot=config_snapshot or {},
            )
        )
        for log in state.turn_logs:
            db.add(
                Turn(
                    session_id=state.session_id,
                    turn=log.turn,
                    speaker=log.speaker,
                    message=log.message,
                    phase=log.phase.value,
                    tone=log.tone,
                    engagement=log.engagement,
                    signals=log.signals_detected,
                )
            )
        for e in state.evidence:
            db.add(
                Evidence(
                    session_id=state.session_id,
                    trait=e.trait,
                    direction=e.direction,
                    signal=e.signal,
                    interpretation=e.interpretation,
                    evidence_strength=e.evidence_strength,
                    conversation_turn=e.conversation_turn,
                )
            )
        for name, est in state.trait_estimates.items():
            for turn_idx, score in enumerate(est.score_history, start=1):
                db.add(
                    TraitSnapshot(
                        session_id=state.session_id,
                        turn=turn_idx,
                        trait=name,
                        score=score,
                        confidence=round(est.confidence, 4),
                    )
                )
        if pred:
            db.add(
                Prediction(
                    session_id=state.session_id,
                    predicted_outcome=pred.predicted_outcome.value,
                    confidence=pred.prediction_confidence,
                    principles=[p.value for p in pred.principles_used],
                    reasoning=pred.reasoning,
                )
            )
        if ev:
            db.add(
                OutcomeRow(
                    session_id=state.session_id,
                    outcome=ev.outcome.value,
                    confidence=ev.confidence,
                    rationale=ev.rationale,
                    resistance_signals=[s.model_dump(mode="json") for s in ev.resistance_signals],
                )
            )
        if state.questionnaire:
            q = state.questionnaire
            db.add(
                Questionnaire(
                    session_id=state.session_id,
                    answered=q.get("answered", 0),
                    complete=q.get("complete", False),
                    responses={str(k): v for k, v in q.get("responses", {}).items()},
                    scores_1_5=q.get("scores_1_5", {}),
                    scores_0_1=q.get("scores_0_1", {}),
                )
            )
        for rec in llm_calls or []:
            data = rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)
            db.add(
                LLMCall(
                    session_id=data.get("session_id") or state.session_id,
                    role=data.get("role", ""),
                    node=data.get("node", ""),
                    model=data.get("model", ""),
                    kind=data.get("kind", ""),
                    latency_ms=data.get("latency_ms", 0.0),
                    ok=data.get("ok", True),
                    parse_ok=data.get("parse_ok"),
                    error=data.get("error"),
                )
            )
        db.commit()
    logger.info("persisted session {} to {}", state.session_id, settings.database_url)


def _purge_session(db: DBSession, session_id: str) -> None:
    for model in (Turn, Evidence, TraitSnapshot, Prediction, OutcomeRow, Questionnaire, LLMCall):
        db.exec(delete(model).where(model.session_id == session_id))
    obj = db.get(Session, session_id)
    if obj is not None:
        db.delete(obj)


def delete_session(session_id: str, settings: Settings | None = None) -> bool:
    engine = get_engine(settings)
    with DBSession(engine) as db:
        obj = db.get(Session, session_id)
        _purge_session(db, session_id)
        db.commit()
        return obj is not None


def delete_participant_data(participant_id: str, settings: Settings | None = None) -> int:
    """'Delete my data': remove every session for a participant and the participant row."""
    engine = get_engine(settings)
    with DBSession(engine) as db:
        sessions = db.exec(select(Session).where(Session.participant_id == participant_id)).all()
        settings = settings or get_settings()
        for s in sessions:
            _purge_session(db, s.id)
            delete_checkpoint(s.id, settings.output_dir)  # the checkpoint holds the chat too
        participant = db.get(Participant, participant_id)
        if participant is not None:
            db.delete(participant)
        db.commit()
        return len(sessions)


def export_session(session_id: str, settings: Settings | None = None) -> dict | None:
    engine = get_engine(settings)
    with DBSession(engine) as db:
        session = db.get(Session, session_id)
        if session is None:
            return None
        payload = {"session": session.model_dump(mode="json")}
        for key, model in (
            ("turns", Turn),
            ("evidence", Evidence),
            ("trait_snapshots", TraitSnapshot),
            ("predictions", Prediction),
            ("outcomes", OutcomeRow),
            ("questionnaires", Questionnaire),
            ("llm_calls", LLMCall),
        ):
            rows = db.exec(select(model).where(model.session_id == session_id)).all()
            payload[key] = [r.model_dump(mode="json") for r in rows]
        return payload


def export_sessions_csv(settings: Settings | None = None) -> str:
    """Flat one-row-per-session CSV for quick spreadsheet analysis."""
    engine = get_engine(settings)
    with DBSession(engine) as db:
        sessions = db.exec(select(Session)).all()
    buffer = io.StringIO()
    fields = [
        "id", "participant_id", "experiment_id", "selection_mode", "principle",
        "turn_count", "profile_stability", "real_outcome", "twin_outcome", "match_flag",
        "aborted", "completion_reason",
    ]
    trait_fields = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]
    header = fields + [f"inferred_{t}" for t in trait_fields] + [f"self_{t}" for t in trait_fields]
    writer = csv.writer(buffer)
    writer.writerow(header)
    for s in sessions:
        row = [getattr(s, f) for f in fields]
        row += [s.inferred_profile.get(t, "") for t in trait_fields]
        row += [s.self_report_profile.get(t, "") for t in trait_fields]
        writer.writerow(row)
    return buffer.getvalue()


def write_json_export(session_id: str, path: Path, settings: Settings | None = None) -> Path | None:
    payload = export_session(session_id, settings)
    if payload is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
