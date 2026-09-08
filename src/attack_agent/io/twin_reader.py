import json
import re

from loguru import logger

from attack_agent.schemas import Outcome, StrategyPrinciple, TwinPrediction


def _parse_outcome(value: str) -> Outcome:
    cleaned = value.strip().strip('"').upper()
    for outcome in Outcome:
        if outcome.value == cleaned:
            return outcome
    lowered = cleaned.lower()
    if "success" in lowered:
        return Outcome.SUCCESS
    if "fail" in lowered:
        return Outcome.FAILURE
    return Outcome.PARTIAL


def _parse_principles(value: str) -> list[StrategyPrinciple]:
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [StrategyPrinciple(str(item).strip().lower()) for item in parsed]
    except (json.JSONDecodeError, ValueError):
        pass
    names = re.findall(r"[a-zA-Z_]+", value.lower())
    principles = []
    for name in names:
        try:
            principles.append(StrategyPrinciple(name))
        except ValueError:
            continue
    return principles


def parse_prediction_text(text: str) -> TwinPrediction | None:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return TwinPrediction.model_validate(
                {
                    "predicted_outcome": _parse_outcome(str(data.get("predicted_outcome", "PARTIAL"))).value,
                    "prediction_confidence": float(data.get("prediction_confidence", 0.5)),
                    "principles_used": [p.value for p in _parse_principles(json.dumps(data.get("principles_used", [])))],
                    "reasoning": str(data.get("reasoning", "")),
                }
            )
    except (json.JSONDecodeError, ValueError):
        pass

    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z_]+)\s*:\s*(.+)$", line.strip())
        if match:
            fields[match.group(1).upper()] = match.group(2).strip()
    if not fields:
        return None
    return TwinPrediction(
        predicted_outcome=(
            _parse_outcome(fields["PREDICTED_OUTCOME"])
            if "PREDICTED_OUTCOME" in fields
            else Outcome.PARTIAL
        ),
        prediction_confidence=(
            float(re.sub(r"[^0-9.]", "", fields["PREDICTION_CONFIDENCE"]) or 0.5)
            if "PREDICTION_CONFIDENCE" in fields
            else 0.5
        ),
        principles_used=_parse_principles(fields.get("PRINCIPLES_USED", "")),
        reasoning=fields.get("REASONING", ""),
    )


def read_twin_prediction(path) -> TwinPrediction | None:
    from pathlib import Path

    path = Path(path)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    prediction = parse_prediction_text(text)
    if prediction is None:
        logger.warning("twin prediction file present but unparseable: {}", path)
    return prediction
