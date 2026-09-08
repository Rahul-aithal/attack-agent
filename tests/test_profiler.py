from attack_agent.engine.profiler import PersonalityProfiler
from attack_agent.engine.validator import ProfileValidator
from attack_agent.schemas import BehavioralEvidence
from attack_agent.state import AgentState


def make_state(turns: int = 12) -> AgentState:
    state = AgentState(session_id="test")
    state.init_traits()
    state.turn_count = turns
    return state


def test_update_from_evidence_moves_scores():
    profiler = PersonalityProfiler()
    state = make_state()
    evidence = [
        BehavioralEvidence(
            trait="openness",
            signal="curiosity",
            direction="high",
            evidence_strength=0.9,
            conversation_turn=1,
        )
    ]
    updates = profiler.update_from_evidence(state, evidence, turn=1)
    assert updates["openness"] > 0
    assert state.trait_estimates["openness"].score > 0.5
    assert state.trait_estimates["openness"].evidence_count == 1


def test_low_direction_decreases_score():
    profiler = PersonalityProfiler()
    state = make_state()
    evidence = [
        BehavioralEvidence(
            trait="agreeableness",
            signal="hostile",
            direction="low",
            evidence_strength=0.9,
            conversation_turn=1,
        )
    ]
    profiler.update_from_evidence(state, evidence, turn=1)
    assert state.trait_estimates["agreeableness"].score < 0.5


def test_confidence_grows_with_evidence_count():
    profiler = PersonalityProfiler()
    state = make_state()
    for turn in range(1, 6):
        evidence = [
            BehavioralEvidence(
                trait="openness",
                signal="curiosity",
                direction="high",
                evidence_strength=0.7,
                conversation_turn=turn,
            )
        ]
        profiler.update_from_evidence(state, evidence, turn=turn)
    conf = state.trait_estimates["openness"].confidence
    assert conf > 0.7
    assert conf <= 0.95


def test_stability_high_when_scores_stable():
    profiler = PersonalityProfiler()
    state = make_state()
    for turn in range(1, 6):
        evidence = [
            BehavioralEvidence(
                trait="openness",
                signal="curiosity",
                direction="high",
                evidence_strength=0.3,
                conversation_turn=turn,
            )
        ]
        profiler.update_from_evidence(state, evidence, turn=turn)
    stability = profiler.compute_stability(state)
    assert stability > 0.8


def test_validator_incomplete_when_few_turns():
    validator = ProfileValidator()
    state = make_state(turns=2)
    complete, reason = validator.evaluate(state)
    assert not complete
    assert reason["turns_ok"] is False


def test_validator_forced_by_max_turns():
    validator = ProfileValidator()
    state = make_state(turns=25)
    complete, reason = validator.evaluate(state)
    assert complete
    assert reason["forced_by_max_turns"] is True


def test_validator_complete_with_good_profile():
    validator = ProfileValidator()
    profiler = PersonalityProfiler()
    state = make_state(turns=12)
    for turn in range(1, 13):
        evidence = [
            BehavioralEvidence(
                trait=trait,
                signal="sig",
                direction="high",
                evidence_strength=0.3,
                conversation_turn=turn,
            )
            for trait in state.trait_estimates
        ]
        profiler.update_from_evidence(state, evidence, turn=turn)
    profiler.compute_stability(state)
    complete, reason = validator.evaluate(state)
    assert complete
    assert reason["confidence_ok"] and reason["stability_ok"]
