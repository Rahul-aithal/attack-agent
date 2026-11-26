"""Personality profilers.

``BetaProfiler`` (v2, default) keeps a Beta(alpha, beta) posterior per trait. High-direction
evidence adds weighted mass to alpha, low-direction to beta; the trait score is the posterior mean
alpha/(alpha+beta). Confidence combines an evidence-count term (rises as more evidence arrives)
with an agreement term (falls when high and low evidence contradict each other), so a trait with
5 "high" and 5 "low" signals is *less* confident than one with 5 consistent signals, even though
both have the same count. ``V1Profiler`` is the original hand-tuned update, kept for ablations.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

from attack_agent.config import Settings, get_settings
from attack_agent.schemas import BehavioralEvidence
from attack_agent.state import AgentState


class BaseProfiler(ABC):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @abstractmethod
    def _apply(self, estimate, ev: BehavioralEvidence) -> None: ...

    @abstractmethod
    def update_confidence(self, state: AgentState) -> None: ...

    def update_from_evidence(
        self, state: AgentState, evidence: list[BehavioralEvidence], turn: int
    ) -> dict[str, float]:
        state.init_traits()
        updates: dict[str, float] = {}
        for ev in evidence:
            estimate = state.trait_estimates[ev.trait]
            old = estimate.score
            self._apply(estimate, ev)
            estimate.evidence_count += 1
            estimate.last_updated_turn = turn
            estimate.score_history.append(round(estimate.score, 4))
            state.evidence.append(ev)
            updates[ev.trait] = round(estimate.score - old, 4)
        self.update_confidence(state)
        return updates

    def compute_stability(self, state: AgentState) -> float:
        window = self.settings.stability_window
        scale = self.settings.stability_scale
        stabilities = []
        for estimate in state.trait_estimates.values():
            if estimate.evidence_count == 0:
                continue
            history = estimate.score_history[-window:]
            if len(history) < 2:
                stabilities.append(0.5)
                continue
            mean = sum(history) / len(history)
            std = math.sqrt(sum((x - mean) ** 2 for x in history) / len(history))
            stabilities.append(max(0.0, 1.0 - std * scale))
        state.profile_stability = sum(stabilities) / len(stabilities) if stabilities else 0.0
        return state.profile_stability


class BetaProfiler(BaseProfiler):
    def _apply(self, estimate, ev: BehavioralEvidence) -> None:
        weight = self.settings.beta_evidence_weight * ev.evidence_strength
        if ev.direction == "high":
            estimate.alpha += weight
            estimate.high_mass += weight
        else:
            estimate.beta += weight
            estimate.low_mass += weight
        estimate.score = estimate.alpha / (estimate.alpha + estimate.beta)

    def update_confidence(self, state: AgentState) -> None:
        rate = self.settings.v1_confidence_rate
        cap = self.settings.max_confidence
        for estimate in state.trait_estimates.values():
            mass = estimate.high_mass + estimate.low_mass
            if mass <= 0:
                estimate.confidence = 0.0
                continue
            count_term = 1.0 - math.exp(-rate * mass)
            agreement = abs(estimate.high_mass - estimate.low_mass) / mass
            agreement = 1.0 - (1.0 - agreement) * self.settings.beta_contradiction_penalty * 2.0
            agreement = max(0.0, min(1.0, agreement))
            estimate.confidence = min(cap, count_term * agreement)


class V1Profiler(BaseProfiler):
    """Original multiplicative update + exponential confidence (ablation baseline)."""

    def _apply(self, estimate, ev: BehavioralEvidence) -> None:
        delta = ev.evidence_strength * self.settings.v1_step
        if ev.direction == "high":
            estimate.score = min(1.0, estimate.score + (1.0 - estimate.score) * delta)
        else:
            estimate.score = max(0.0, estimate.score - estimate.score * delta)

    def update_confidence(self, state: AgentState) -> None:
        rate = self.settings.v1_confidence_rate
        cap = self.settings.max_confidence
        for estimate in state.trait_estimates.values():
            estimate.confidence = min(cap, 1.0 - math.exp(-rate * estimate.evidence_count))


def make_profiler(settings: Settings | None = None) -> BaseProfiler:
    settings = settings or get_settings()
    if settings.profiler_version == "v1":
        return V1Profiler(settings)
    return BetaProfiler(settings)


# Backwards-compatible alias (tests and older imports expect PersonalityProfiler).
PersonalityProfiler = BetaProfiler
