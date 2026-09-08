from attack_agent.config import Settings, get_settings
from attack_agent.state import AgentState


class ProfileValidator:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def evaluate(self, state: AgentState) -> tuple[bool, dict]:
        confidences = {
            name: estimate.confidence for name, estimate in state.trait_estimates.items()
        }
        avg_confidence = sum(confidences.values()) / len(confidences) if confidences else 0.0
        traits_above = sum(
            1 for conf in confidences.values() if conf >= self.settings.trait_confidence_threshold
        )
        turns_ok = state.turn_count >= self.settings.min_turns
        evidence_ok = traits_above >= self.settings.min_traits_above_threshold
        confidence_ok = avg_confidence >= self.settings.avg_confidence_threshold
        stability_ok = state.profile_stability >= self.settings.stability_threshold
        forced = state.turn_count >= self.settings.max_turns

        complete = (turns_ok and evidence_ok and confidence_ok and stability_ok) or forced
        reason = {
            "turn_count": state.turn_count,
            "min_turns_required": self.settings.min_turns,
            "turns_ok": turns_ok,
            "traits_with_sufficient_confidence": traits_above,
            "min_traits_required": self.settings.min_traits_above_threshold,
            "evidence_ok": evidence_ok,
            "avg_trait_confidence": round(avg_confidence, 3),
            "avg_confidence_required": self.settings.avg_confidence_threshold,
            "confidence_ok": confidence_ok,
            "profile_stability": round(state.profile_stability, 3),
            "stability_required": self.settings.stability_threshold,
            "stability_ok": stability_ok,
            "forced_by_max_turns": forced,
        }
        if forced and not (turns_ok and evidence_ok and confidence_ok):
            reason["note"] = "profile completed by max-turn fallback; confidence may be low"
        return complete, reason