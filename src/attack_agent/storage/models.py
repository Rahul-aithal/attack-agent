"""SQLModel tables for persistent research data.

A pseudonymous ``Participant`` owns many ``Session`` rows. Per-session detail is normalised into
``Turn``, ``Evidence``, ``TraitSnapshot``, ``Prediction``, ``Outcome``, ``Questionnaire`` and
``LLMCall`` so the analysis scripts can query across sessions without re-parsing JSON blobs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import JSON, Column, Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class Participant(SQLModel, table=True):
    __tablename__ = "participants"
    id: str = Field(primary_key=True)  # pseudonymous id, never PII
    label: str = ""
    created_at: datetime = Field(default_factory=_now)
    is_synthetic: bool = False
    known_traits: dict[str, float] | None = Field(default=None, sa_column=Column(JSON))


class Session(SQLModel, table=True):
    __tablename__ = "sessions"
    id: str = Field(primary_key=True)
    participant_id: str | None = Field(default=None, foreign_key="participants.id", index=True)
    experiment_id: str | None = Field(default=None, index=True)
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    phase: str = "profiling"
    turn_count: int = 0
    completion_reason: str = ""
    profile_stability: float = 0.0
    selection_mode: str = ""
    principle: str | None = None
    real_outcome: str | None = None
    twin_outcome: str | None = None
    match_flag: bool | None = None
    aborted: bool = False
    inferred_profile: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    inferred_confidence: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    self_report_profile: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    config_snapshot: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Turn(SQLModel, table=True):
    __tablename__ = "turns"
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    turn: int = 0
    speaker: str = ""
    message: str = ""
    phase: str = ""
    tone: str = ""
    engagement: float = 0.0
    signals: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class Evidence(SQLModel, table=True):
    __tablename__ = "evidence"
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    trait: str = ""
    direction: str = ""
    signal: str = ""
    interpretation: str = ""
    evidence_strength: float = 0.0
    conversation_turn: int = 0


class TraitSnapshot(SQLModel, table=True):
    __tablename__ = "trait_snapshots"
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    turn: int = 0
    trait: str = ""
    score: float = 0.0
    confidence: float = 0.0


class Prediction(SQLModel, table=True):
    __tablename__ = "predictions"
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    predicted_outcome: str = ""
    confidence: float = 0.0
    principles: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    reasoning: str = ""


class OutcomeRow(SQLModel, table=True):
    __tablename__ = "outcomes"
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    outcome: str = ""
    confidence: float = 0.0
    rationale: str = ""
    resistance_signals: list[dict] = Field(default_factory=list, sa_column=Column(JSON))


class Questionnaire(SQLModel, table=True):
    __tablename__ = "questionnaires"
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    answered: int = 0
    complete: bool = False
    responses: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    scores_1_5: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    scores_0_1: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))


class LLMCall(SQLModel, table=True):
    __tablename__ = "llm_calls"
    id: int | None = Field(default=None, primary_key=True)
    session_id: str | None = Field(default=None, index=True)
    role: str = ""
    node: str = ""
    model: str = ""
    kind: str = ""
    latency_ms: float = 0.0
    ok: bool = True
    parse_ok: bool | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
