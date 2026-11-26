"""IPIP-50 scoring. Given raw 1-5 responses keyed by item id, produce per-trait scores on both
the native 1-5 scale and the 0-1 scale used internally, so inferred and self-report profiles line
up directly for the accuracy analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from attack_agent.data.ipip50 import IPIP50, LIKERT_MAX, LIKERT_MIN, IPIPItem
from attack_agent.schemas import ALL_TRAITS


@dataclass
class QuestionnaireResult:
    responses: dict[int, int]
    scores_1_5: dict[str, float] = field(default_factory=dict)
    scores_0_1: dict[str, float] = field(default_factory=dict)
    answered: int = 0
    complete: bool = False

    def to_dict(self) -> dict:
        return {
            "responses": {str(k): v for k, v in self.responses.items()},
            "scores_1_5": self.scores_1_5,
            "scores_0_1": self.scores_0_1,
            "answered": self.answered,
            "complete": self.complete,
        }


def _score_item(item: IPIPItem, raw: int) -> float:
    raw = max(LIKERT_MIN, min(LIKERT_MAX, int(raw)))
    return float(LIKERT_MAX + LIKERT_MIN - raw) if item.keyed == "-" else float(raw)


def score_responses(responses: dict[int, int]) -> QuestionnaireResult:
    """`responses` maps IPIP item id -> 1-5. Missing items are ignored (trait mean over answered)."""
    valid_ids = {item.id for item in IPIP50}
    clean: dict[int, int] = {}
    for k, v in (responses.items() if isinstance(responses, dict) else []):
        try:
            item_id, value = int(k), int(v)
        except (TypeError, ValueError):
            continue  # malformed entry from a client: ignore rather than crash the session
        if item_id in valid_ids and LIKERT_MIN <= value <= LIKERT_MAX:
            clean[item_id] = value
    responses = clean
    per_trait: dict[str, list[float]] = {t: [] for t in ALL_TRAITS}
    for item in IPIP50:
        if item.id in responses:
            per_trait[item.trait].append(_score_item(item, responses[item.id]))
    scores_1_5: dict[str, float] = {}
    scores_0_1: dict[str, float] = {}
    for trait, values in per_trait.items():
        if values:
            mean = sum(values) / len(values)
            scores_1_5[trait] = round(mean, 3)
            scores_0_1[trait] = round((mean - LIKERT_MIN) / (LIKERT_MAX - LIKERT_MIN), 3)
    return QuestionnaireResult(
        responses=responses,
        scores_1_5=scores_1_5,
        scores_0_1=scores_0_1,
        answered=len(responses),
        complete=len(responses) == len(IPIP50),
    )


def questionnaire_items() -> list[dict]:
    """Serialisable item list for the API / UI (ordering preserved, no keying leaked to UI)."""
    return [{"id": i.id, "text": i.text} for i in IPIP50]
