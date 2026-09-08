from typing import Literal

from pydantic import BaseModel, Field

TraitName = Literal[
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
]

ALL_TRAITS: list[TraitName] = [
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
]


class BehavioralEvidence(BaseModel):
    trait: TraitName
    signal: str
    direction: Literal["high", "low"] = "high"
    evidence_strength: float = Field(ge=0.0, le=1.0)
    conversation_turn: int
    interpretation: str = ""


class TraitEstimate(BaseModel):
    trait: TraitName
    score: float = 0.5
    confidence: float = 0.0
    evidence_count: int = 0
    last_updated_turn: int = 0
    score_history: list[float] = Field(default_factory=list)
