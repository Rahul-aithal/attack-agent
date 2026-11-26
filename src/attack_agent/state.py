from datetime import UTC, datetime

from pydantic import BaseModel, Field

from attack_agent.schemas import (
    ALL_TRAITS,
    BehavioralEvidence,
    Outcome,
    OutcomeEvaluation,
    Phase,
    StrategyPrinciple,
    TraitEstimate,
    TurnLog,
    TwinPrediction,
)


class AgentState(BaseModel):
    session_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
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
    scenario_exchanges: list[dict[str, str]] = Field(default_factory=list)
    questionnaire: dict | None = None
    self_report_scores: dict[str, float] = Field(default_factory=dict)
    consent_given: bool = False
    aborted: bool = False
    # Researcher steering (focus a trait, one-off instruction, end profiling early). Logged so
    # steered sessions can be flagged or excluded in the analysis.
    interventions: list[dict] = Field(default_factory=list)
    # "mobile" | "desktop", reported by the participant's browser; message length adapts to it
    # and it is stored with the session (device can affect how people respond).
    device: str | None = None
    # Conversation memory: every question the agent asked, the participant's answer and the topic
    # (trait) it was exploring. Fed back to the agent so it builds on answers instead of asking
    # again; stored with the session and shown in reports.
    memory: list[dict] = Field(default_factory=list)
    # which example angles (per trait) have already been suggested, so they are not reused
    used_angles: dict[str, list[int]] = Field(default_factory=dict)
    # ---- resume support (the session is checkpointed to outputs/checkpoints/<id>.json) ----
    join_code: str | None = None
    # why an aborted session ended: participant_quit | participant_timeout | researcher
    abort_reason: str | None = None
    phase_before_abort: Phase | None = None
    # index into conversation_history where the scenario began (to redo it cleanly on resume)
    sim_history_start: int | None = None

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
