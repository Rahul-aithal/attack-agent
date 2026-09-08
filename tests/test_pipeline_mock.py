import pytest

from attack_agent.engine.llm import extract_json
from attack_agent.io.session_logger import write_session_log
from attack_agent.io.twin_writer import write_twin_data
from attack_agent.engine.strategy_selector import select_principle
from attack_agent.schemas import (
    Outcome,
    StrategyPrinciple,
    TwinPrediction,
    TurnLog,
)
from attack_agent.state import AgentState


FAKE_ANALYSIS = {
    "signals": [
        {
            "trait": "agreeableness",
            "signal": "cooperative language",
            "direction": "high",
            "evidence_strength": 0.8,
            "interpretation": "willing to help",
        },
        {
            "trait": "conscientiousness",
            "signal": "mentions checking work",
            "direction": "high",
            "evidence_strength": 0.6,
            "interpretation": "verification habit",
        },
    ],
    "tone": "friendly",
    "engagement": 0.7,
    "resistance": [],
}


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def chat_text(self, messages, temperature=None):
        self.calls += 1
        return "That's really interesting, tell me more about how you plan your week?"

    async def chat_json(self, messages, temperature=None):
        self.calls += 1
        return dict(FAKE_ANALYSIS)


@pytest.mark.asyncio
async def test_extract_json_handles_noise():
    text = 'Sure! Here is the analysis: {"signals": [], "tone": "calm", "engagement": 0.5} hope that helps'
    data = extract_json(text)
    assert data is not None
    assert data["tone"] == "calm"


@pytest.mark.asyncio
async def test_react_loop_processes_turns():
    from attack_agent.react.loop import ReActLoop

    state = AgentState(session_id="sess_mock")
    state.init_traits()
    loop = ReActLoop(FakeLLM())

    for _ in range(10):
        result = await loop.process_turn(state, "I love planning my week and helping friends")
        assert result["agent_reply"]

    assert state.turn_count == 10
    assert state.trait_estimates["agreeableness"].evidence_count == 10
    assert state.trait_estimates["conscientiousness"].evidence_count == 10
    assert state.trait_estimates["agreeableness"].confidence > 0.9
    assert len(state.evidence) == 20
    assert len(state.turn_logs) == 10


@pytest.mark.asyncio
async def test_full_session_flow(tmp_path):
    from attack_agent.react.loop import ReActLoop

    state = AgentState(session_id="sess_mock_full")
    state.init_traits()
    loop = ReActLoop(FakeLLM())

    for _ in range(12):
        await loop.process_turn(state, "I usually double-check things and enjoy meeting people")

    path = write_twin_data(state, output_dir=tmp_path)
    assert path.exists()
    assert "BIG_FIVE" in path.read_text(encoding="utf-8")

    prediction = TwinPrediction(
        predicted_outcome=Outcome.PARTIAL,
        prediction_confidence=0.78,
        principles_used=[StrategyPrinciple.AUTHORITY],
        reasoning="test",
    )
    state.twin_prediction = prediction
    principle, reason, effectiveness = select_principle(state, prediction)
    assert principle == StrategyPrinciple.AUTHORITY
    assert reason
    assert 0 <= effectiveness <= 1

    state.current_principle = principle
    state.real_outcome = Outcome.PARTIAL
    state.match_flag = state.real_outcome == prediction.predicted_outcome
    log_path = write_session_log(state, output_dir=tmp_path)
    assert log_path.exists()

    import json

    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["match_flag"] is True
    assert data["turn_count"] == 12
    assert data["twin_prediction"]["predicted_outcome"] == "PARTIAL"


def test_selector_falls_back_to_authority():
    state = AgentState(session_id="s")
    state.init_traits()
    principle, reason, _ = select_principle(state, None)
    assert principle == StrategyPrinciple.AUTHORITY
    assert "default" in reason
