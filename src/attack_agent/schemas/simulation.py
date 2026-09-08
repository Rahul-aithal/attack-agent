from enum import Enum

from pydantic import BaseModel, Field


class StrategyPrinciple(str, Enum):
    RECIPROCITY = "reciprocity"
    COMMITMENT_CONSISTENCY = "commitment_consistency"
    SOCIAL_PROOF = "social_proof"
    LIKING = "liking"
    AUTHORITY = "authority"
    SCARCITY = "scarcity"


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILURE = "FAILURE"
    INCOMPLETE = "INCOMPLETE"


class TwinPrediction(BaseModel):
    predicted_outcome: Outcome = Outcome.PARTIAL
    prediction_confidence: float = 0.5
    principles_used: list[StrategyPrinciple] = Field(default_factory=list)
    reasoning: str = ""


class ResistanceSignal(BaseModel):
    signal_type: str
    confidence: float = 0.5
    turn_number: int = 0
    description: str = ""


class OutcomeEvaluation(BaseModel):
    outcome: Outcome = Outcome.INCOMPLETE
    confidence: float = 0.5
    rationale: str = ""
    resistance_signals: list[ResistanceSignal] = Field(default_factory=list)
