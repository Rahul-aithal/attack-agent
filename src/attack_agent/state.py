from datetime import datetime, timezone

from pydantic import BaseModel, Field

from attack_agent.schemas import (
    ALL_TRAITS,
    BehavioralEvidence,
    Outcome,
    OutcomeEvaluation,
    Phase,
    StrategyPrinciple,
    TraitEstimate,
    TwinPrediction,
    TurnLog,
)


class AgentState(BaseModel):
    session_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    phase: Phase = Phase.PROFILING
    turn_count: int = 0
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    turn_logs: list[TurnLog] = Field(default_factory=list)
    evidence: list[BehavioralEvidence] = Field(default_factory=list)
    trait_estimates: dict[str, TraitEstimate] = Field(default_factory=dict)
    profile_stability: float = 0.0
    profile_complete: bool = False
    completion_reason: str = ""
    twin_data_written: bool = False
    twin_prediction: TwinPrediction | None = None
    current_principle: StrategyPrinciple | None = None
    scenario_message: str | None = None
    real_outcome: Outcome | None = None
    outcome_evaluation: OutcomeEvaluation | None = None
    match_flag: bool | None = None

    def init_traits(self) -> None:
        if not self.trait_estimates:
            for trait in ALL_TRAITS:
                self.trait_estimates[trait] = TraitEstimate(trait=trait)

    def avg_confidence(self) -> float:
        if not self.trait_estimates:
            return 0.0
        return sum(e.confidence for e in self.trait_estimates.values()) / len(
            self.trait_estimates
        )
