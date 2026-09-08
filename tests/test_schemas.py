import pytest

from attack_agent.schemas import (
    BehavioralEvidence,
    Outcome,
    OutcomeEvaluation,
    Phase,
    StrategyPrinciple,
    TraitEstimate,
    TwinPrediction,
    TurnLog,
)


def test_behavioral_evidence_valid():
    ev = BehavioralEvidence(
        trait="openness",
        signal="curious about topic",
        direction="high",
        evidence_strength=0.8,
        conversation_turn=3,
        interpretation="asked why",
    )
    assert ev.trait == "openness"
    assert 0 <= ev.evidence_strength <= 1


def test_behavioral_evidence_rejects_bad_trait():
    with pytest.raises(Exception):
        BehavioralEvidence(
            trait="humor",
            signal="x",
            evidence_strength=0.5,
            conversation_turn=1,
        )


def test_behavioral_evidence_rejects_out_of_range_strength():
    with pytest.raises(Exception):
        BehavioralEvidence(
            trait="openness",
            signal="x",
            evidence_strength=1.5,
            conversation_turn=1,
        )


def test_trait_estimate_defaults():
    est = TraitEstimate(trait="agreeableness")
    assert est.score == 0.5
    assert est.confidence == 0.0
    assert est.evidence_count == 0


def test_twin_prediction_defaults():
    p = TwinPrediction()
    assert p.predicted_outcome == Outcome.PARTIAL
    assert p.prediction_confidence == 0.5


def test_outcome_evaluation_roundtrip():
    ev = OutcomeEvaluation(
        outcome=Outcome.SUCCESS,
        confidence=0.8,
        rationale="completed task",
    )
    data = ev.model_dump(mode="json")
    assert OutcomeEvaluation.model_validate(data).outcome == Outcome.SUCCESS


def test_turn_log_defaults():
    log = TurnLog(turn=1, speaker="participant", message="hi")
    assert log.phase == Phase.PROFILING
    assert log.signals_detected == []


def test_strategy_principles():
    assert len(StrategyPrinciple) == 6
    assert StrategyPrinciple("authority") == StrategyPrinciple.AUTHORITY
