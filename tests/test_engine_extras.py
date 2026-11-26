import pytest

from attack_agent.config import Settings
from attack_agent.engine.llm import Route, Router
from attack_agent.engine.profiler import BetaProfiler
from attack_agent.engine.questionnaire import score_responses
from attack_agent.engine.session_engine import SessionEngine
from attack_agent.engine.simulator import scenario_is_safe
from attack_agent.schemas import BehavioralEvidence
from attack_agent.state import AgentState
from tests.fakes import FakeProvider

DOMAIN = "portal.simulated-link.example.com"


# ----------------------------------------------------------------- safety filter
def test_safety_rejects_password_request():
    ok, _ = scenario_is_safe("Please send your password to verify.", DOMAIN)
    assert not ok


def test_safety_rejects_real_url():
    ok, reason = scenario_is_safe("Log in at https://evil-example.net/login now.", DOMAIN)
    assert not ok
    assert "URL" in reason


def test_safety_allows_simulated_domain():
    ok, _ = scenario_is_safe(f"Open {DOMAIN} and confirm your asset ID.", DOMAIN)
    assert ok


# ----------------------------------------------------------------- questionnaire
def test_questionnaire_all_fives():
    result = score_responses({i: 5 for i in range(1, 51)})
    assert result.complete
    # reverse-keyed items pull some traits below the max; every score within range
    assert all(1.0 <= v <= 5.0 for v in result.scores_1_5.values())
    assert set(result.scores_0_1) == {
        "openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"
    }


def test_questionnaire_reverse_keying():
    # item 6 "Don't talk a lot" is reverse-keyed extraversion; answering 1 => high extraversion
    result = score_responses({6: 1})
    assert result.scores_1_5["extraversion"] == 5.0


# ----------------------------------------------------------------- beta profiler
def test_beta_confidence_drops_with_contradiction():
    profiler = BetaProfiler(Settings())
    consistent = AgentState(session_id="c")
    consistent.init_traits()
    contradictory = AgentState(session_id="x")
    contradictory.init_traits()
    for turn in range(1, 7):
        profiler.update_from_evidence(
            consistent,
            [BehavioralEvidence(trait="openness", signal="s", direction="high",
                                evidence_strength=0.7, conversation_turn=turn)],
            turn,
        )
        direction = "high" if turn % 2 == 0 else "low"
        profiler.update_from_evidence(
            contradictory,
            [BehavioralEvidence(trait="openness", signal="s", direction=direction,
                                evidence_strength=0.7, conversation_turn=turn)],
            turn,
        )
    assert (
        consistent.trait_estimates["openness"].confidence
        > contradictory.trait_estimates["openness"].confidence
    )


# ----------------------------------------------------------------- full session
def _router() -> Router:
    node = FakeProvider("fake")
    roles = {r: [Route("fake", "m")] for r in
             ["agent", "extractor", "twin", "judge", "sim_participant"]}
    return Router({"fake": node}, roles, Settings(min_turns=2, max_turns=3, health_cache_seconds=0))


@pytest.mark.asyncio
async def test_full_session_runs_to_complete(tmp_path):
    settings = Settings(
        min_turns=2, max_turns=3, health_cache_seconds=0,
        output_dir=tmp_path, twin_enabled=True, questionnaire_enabled=True,
    )
    node = FakeProvider("fake")
    roles = {r: [Route("fake", "m")] for r in
             ["agent", "extractor", "twin", "judge", "sim_participant"]}
    router = Router({"fake": node}, roles, settings)
    engine = SessionEngine(router, settings=settings)

    phases_seen = []
    async for event in engine.events():
        t = event["type"]
        if t == "phase_change":
            phases_seen.append(event["phase"])
        elif t == "await_message":
            engine.submit_message("I like to plan ahead and help my friends out.")
        elif t == "await_questionnaire":
            engine.submit_questionnaire({i: 4 for i in range(1, 51)})

    assert "complete" in phases_seen
    assert "profiling" in phases_seen
    assert "simulation" in phases_seen
    assert engine.state.real_outcome is not None
    assert engine.state.questionnaire is not None
    assert engine.state.match_flag is not None


@pytest.mark.asyncio
async def test_session_abort(tmp_path):
    settings = Settings(min_turns=2, max_turns=5, health_cache_seconds=0, output_dir=tmp_path)
    node = FakeProvider("fake")
    roles = {r: [Route("fake", "m")] for r in
             ["agent", "extractor", "twin", "judge", "sim_participant"]}
    router = Router({"fake": node}, roles, settings)
    engine = SessionEngine(router, settings=settings)

    seen_aborted = False
    async for event in engine.events():
        if event["type"] == "await_message":
            engine.abort()
        elif event["type"] == "aborted":
            seen_aborted = True
    assert seen_aborted
    assert engine.state.aborted


@pytest.mark.asyncio
async def test_observer_sees_every_event_including_late_join(tmp_path):
    """A researcher dashboard attached alongside the participant must receive the full stream
    (history replayed if it joins late), not steal events from the participant."""
    import asyncio

    settings = Settings(
        min_turns=2, max_turns=3, health_cache_seconds=0,
        output_dir=tmp_path, twin_enabled=True, questionnaire_enabled=False,
    )
    node = FakeProvider("fake")
    roles = {r: [Route("fake", "m")] for r in
             ["agent", "extractor", "twin", "judge", "sim_participant"]}
    router = Router({"fake": node}, roles, settings)
    engine = SessionEngine(router, settings=settings)

    participant_events: list[str] = []
    observer_events: list[str] = []
    observer_task: asyncio.Task | None = None

    async def observe():
        async for event in engine.events():
            observer_events.append(event["type"])

    async for event in engine.events():
        participant_events.append(event["type"])
        if event["type"] == "await_message":
            if observer_task is None:  # dashboard joins after the session has started
                observer_task = asyncio.create_task(observe())
            engine.submit_message("I like to plan ahead and help my friends out.")
    assert observer_task is not None
    await observer_task

    assert "complete" in participant_events
    assert observer_events == participant_events
    assert "twin_prediction" in observer_events


def _fake_engine(tmp_path, **overrides):
    settings = Settings(
        min_turns=2, max_turns=3, health_cache_seconds=0, output_dir=tmp_path,
        twin_enabled=True, questionnaire_enabled=True, **overrides,
    )
    node = FakeProvider("fake")
    roles = {r: [Route("fake", "m")] for r in
             ["agent", "extractor", "twin", "judge", "sim_participant"]}
    return SessionEngine(Router({"fake": node}, roles, settings), settings=settings)


@pytest.mark.asyncio
async def test_abort_during_scenario_finishes_instead_of_hanging(tmp_path):
    import asyncio

    engine = _fake_engine(tmp_path)
    phases: list[str] = []

    async def drive():
        async for event in engine.events():
            if event["type"] == "phase_change":
                phases.append(event["phase"])
            elif event["type"] == "await_message":
                if event["context"] == "scenario":
                    engine.abort()  # participant closes the tab at the fake request
                else:
                    engine.submit_message("I plan ahead and love helping people")

    await asyncio.wait_for(drive(), timeout=10)
    assert phases[-1] == "aborted"
    assert "questionnaire" not in phases
    assert engine.state.aborted


@pytest.mark.asyncio
async def test_last_profiling_turn_has_no_dangling_agent_question(tmp_path):
    engine = _fake_engine(tmp_path, stopping_rule=False)  # always runs to max_turns=3
    agent_msgs_in_profiling = 0
    phase = ""
    async for event in engine.events():
        if event["type"] == "phase_change":
            phase = event["phase"]
        elif event["type"] == "agent_message" and phase == "profiling":
            agent_msgs_in_profiling += 1
        elif event["type"] == "await_message":
            engine.submit_message("I plan ahead and love helping people")
        elif event["type"] == "await_questionnaire":
            engine.submit_questionnaire({i: 3 for i in range(1, 51)})
    # opening + replies to turns 1 and 2; turn 3 is final, so no reply
    assert agent_msgs_in_profiling == 3
    assert engine.state.conversation_history[0]["role"] == "assistant"  # opening kept


def test_session_settings_reach_the_react_loop(tmp_path):
    from attack_agent.engine.profiler import V1Profiler

    engine = _fake_engine(tmp_path, profiler_version="v1", extractor_mode="keyword")
    assert isinstance(engine.loop.profiler, V1Profiler)
    assert engine.loop.signal_extractor.settings.extractor_mode == "keyword"
    assert engine.loop.validator.settings.max_turns == 3
