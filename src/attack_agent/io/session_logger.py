import json
from datetime import datetime, timezone
from pathlib import Path

from attack_agent.config import Settings, get_settings
from attack_agent.state import AgentState


def build_session_log(state: AgentState):
    from attack_agent.schemas import SessionLog

    return SessionLog(
        session_id=state.session_id,
        start_time=state.started_at,
        end_time=datetime.now(timezone.utc),
        turn_count=state.turn_count,
        profile={
            name: estimate.score for name, estimate in state.trait_estimates.items()
        },
        trait_confidence={
            name: estimate.confidence for name, estimate in state.trait_estimates.items()
        },
        evidence=[ev.model_dump(mode="json") for ev in state.evidence],
        profile_stability=round(state.profile_stability, 4),
        twin_prediction=(
            state.twin_prediction.model_dump(mode="json")
            if state.twin_prediction
            else None
        ),
        scenario_used=(
            state.current_principle.value if state.current_principle else None
        ),
        real_outcome=state.real_outcome.value if state.real_outcome else None,
        outcome_rationale=(
            state.outcome_evaluation.rationale if state.outcome_evaluation else None
        ),
        resistance_signals=(
            [s.model_dump(mode="json") for s in state.outcome_evaluation.resistance_signals]
            if state.outcome_evaluation
            else []
        ),
        match_flag=state.match_flag,
        turns=state.turn_logs,
    )


def write_session_log(state: AgentState, output_dir=None) -> Path:
    settings = get_settings()
    output_dir = Path(output_dir) if output_dir else settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "session_log.json"
    log = build_session_log(state)
    path.write_text(
        json.dumps(log.model_dump(mode="json"), indent=2, default=str), encoding="utf-8"
    )
    return path
