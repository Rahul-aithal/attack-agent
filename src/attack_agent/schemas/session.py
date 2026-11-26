from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Phase(str, Enum):
    INITIALIZATION = "initialization"
    CONSENT = "consent"
    PROFILING = "profiling"
    TWIN_HANDOFF = "twin_handoff"
    SIMULATION = "simulation"
    EVALUATION = "evaluation"
    QUESTIONNAIRE = "questionnaire"
    DEBRIEF = "debrief"
    COMPLETE = "complete"
    ABORTED = "aborted"


class TurnLog(BaseModel):
    turn: int
    speaker: str
    message: str
    signals_detected: list[str] = Field(default_factory=list)
    trait_updates: dict[str, float] = Field(default_factory=dict)
    agent_action: str = ""
    tone: str = ""
    engagement: float = 0.0
    phase: Phase = Phase.PROFILING
    timestamp: datetime = Field(default_factory=datetime.now)


class SessionLog(BaseModel):
    session_id: str
    start_time: datetime
    end_time: datetime | None = None
    turn_count: int = 0
    profile: dict[str, float] = Field(default_factory=dict)
    trait_confidence: dict[str, float] = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list)
    profile_stability: float = 0.0
    twin_prediction: dict | None = None
    scenario_used: str | None = None
    real_outcome: str | None = None
    outcome_rationale: str | None = None
    resistance_signals: list[dict] = Field(default_factory=list)
    match_flag: bool | None = None
    turns: list[TurnLog] = Field(default_factory=list)
    questionnaire: dict | None = None
    self_report_scores: dict[str, float] = Field(default_factory=dict)
    inferred_vs_self_report: dict | None = None
    completion_reason: str = ""
