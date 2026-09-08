from attack_agent.schemas import StrategyPrinciple, TwinPrediction
from attack_agent.state import AgentState

TRAIT_PRINCIPLE_MAP: list[tuple[str, StrategyPrinciple, str]] = [
    ("agreeableness", StrategyPrinciple.LIKING, "high agreeableness favors rapport-based influence"),
    ("conscientiousness", StrategyPrinciple.AUTHORITY, "high conscientiousness respects legitimate procedure"),
    ("extraversion", StrategyPrinciple.SOCIAL_PROOF, "high extraversion is responsive to peer behavior"),
    ("neuroticism", StrategyPrinciple.SCARCITY, "elevated stress sensitivity responds to urgency"),
    ("openness", StrategyPrinciple.RECIPROCITY, "high openness engages with give-and-take framing"),
    ("conscientiousness", StrategyPrinciple.COMMITMENT_CONSISTENCY, "structured individuals prefer consistent follow-through"),
]


def select_principle(
    state: AgentState, prediction: TwinPrediction | None
) -> tuple[StrategyPrinciple, str, float]:
    if prediction and prediction.principles_used:
        principle = prediction.principles_used[0]
        reason = "principle specified in twin prediction"
        return principle, reason, prediction.prediction_confidence

    ranked = sorted(
        state.trait_estimates.items(), key=lambda kv: kv[1].score, reverse=True
    )
    top_trait, top_estimate = ranked[0]
    for trait, principle, reason in TRAIT_PRINCIPLE_MAP:
        if trait == top_trait and top_estimate.score >= 0.55:
            confidence = min(0.9, 0.5 + 0.4 * top_estimate.score * top_estimate.confidence)
            return principle, f"selected from experimental trait-strategy mapping ({reason})", confidence

    return (
        StrategyPrinciple.AUTHORITY,
        "default mapping: no dominant trait signal found",
        0.5,
    )