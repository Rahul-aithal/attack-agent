import json

from attack_agent.io.session_logger import build_session_log, write_session_log
from attack_agent.io.twin_reader import parse_prediction_text, read_twin_prediction
from attack_agent.io.twin_writer import write_twin_data
from attack_agent.schemas import Outcome, StrategyPrinciple, TwinPrediction
from attack_agent.state import AgentState


def make_state() -> AgentState:
    state = AgentState(session_id="sess_test")
    state.init_traits()
    state.turn_count = 10
    state.profile_stability = 0.85
    return state


def test_parse_keyvalue_prediction(tmp_path):
    path = tmp_path / "twin_prediction.txt"
    path.write_text(
        "PREDICTED_OUTCOME: PARTIAL\n"
        "PREDICTION_CONFIDENCE: 0.78\n"
        'PRINCIPLES_USED: ["authority"]\n'
        "REASONING: cautious participant\n",
        encoding="utf-8",
    )
    prediction = read_twin_prediction(path)
    assert prediction is not None
    assert prediction.predicted_outcome == Outcome.PARTIAL
    assert prediction.prediction_confidence == 0.78
    assert prediction.principles_used == [StrategyPrinciple.AUTHORITY]


def test_parse_json_prediction(tmp_path):
    path = tmp_path / "twin_prediction.txt"
    path.write_text(
        json.dumps(
            {
                "predicted_outcome": "SUCCESS",
                "prediction_confidence": 0.82,
                "principles_used": ["social_proof"],
                "reasoning": "outgoing",
            }
        ),
        encoding="utf-8",
    )
    prediction = read_twin_prediction(path)
    assert prediction.predicted_outcome == Outcome.SUCCESS
    assert prediction.principles_used == [StrategyPrinciple.SOCIAL_PROOF]


def test_parse_missing_file_returns_none(tmp_path):
    assert read_twin_prediction(tmp_path / "nope.txt") is None


def test_parse_lenient_outcome():
    prediction = parse_prediction_text("PREDICTED_OUTCOME: success\n")
    assert prediction.predicted_outcome == Outcome.SUCCESS


def test_write_twin_data(tmp_path):
    state = make_state()
    path = write_twin_data(state, output_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "BIG_FIVE" in text
    assert "openness" in text
    assert "sess_test" in text


def test_session_log_roundtrip(tmp_path):
    state = make_state()
    state.twin_prediction = TwinPrediction(predicted_outcome=Outcome.FAILURE)
    state.real_outcome = Outcome.FAILURE
    state.match_flag = True
    state.current_principle = StrategyPrinciple.LIKING
    path = write_session_log(state, output_dir=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["match_flag"] is True
    assert data["real_outcome"] == "FAILURE"
    assert data["scenario_used"] == "liking"
    log = build_session_log(state)
    assert log.turn_count == 10
