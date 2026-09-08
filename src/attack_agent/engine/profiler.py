import math

from attack_agent.config import Settings, get_settings
from attack_agent.schemas import BehavioralEvidence
from attack_agent.state import AgentState


class PersonalityProfiler:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def update_from_evidence(
        self, state: AgentState, evidence: list[BehavioralEvidence], turn: int
    ) -> dict[str, float]:
        state.init_traits()
        updates: dict[str, float] = {}
        for ev in evidence:
            estimate = state.trait_estimates[ev.trait]
            old = estimate.score
            delta = ev.evidence_strength * 0.18
            if ev.direction == "high":
                estimate.score = min(1.0, estimate.score + (1.0 - estimate.score) * delta)
            else:
                estimate.score = max(0.0, estimate.score - estimate.score * delta)
            estimate.evidence_count += 1
            estimate.last_updated_turn = turn
            estimate.score_history.append(round(estimate.score, 4))
            state.evidence.append(ev)
            updates[ev.trait] = round(estimate.score - old, 4)
        self.update_confidence(state)
        return updates

    def update_confidence(self, state: AgentState) -> None:
        for estimate in state.trait_estimates.values():
            estimate.confidence = min(
                0.95, 1.0 - math.exp(-0.35 * estimate.evidence_count)
            )

    def compute_stability(self, state: AgentState) -> float:
        stabilities = []
        for estimate in state.trait_estimates.values():
            if estimate.evidence_count == 0:
                continue
            history = estimate.score_history[-4:]
            if len(history) < 2:
                stabilities.append(0.5)
                continue
            mean = sum(history) / len(history)
            variance = sum((x - mean) ** 2 for x in history) / len(history)
            std = math.sqrt(variance)
            stabilities.append(max(0.0, 1.0 - std * 5.0))
        state.profile_stability = (
            sum(stabilities) / len(stabilities) if stabilities else 0.0
        )
        return state.profile_stability