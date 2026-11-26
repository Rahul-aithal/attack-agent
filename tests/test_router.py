import pytest

from attack_agent.config import Settings
from attack_agent.engine.llm import Route, Router
from tests.fakes import FakeProvider


def make_router(**kwargs) -> Router:
    nodes = {
        "primary": FakeProvider("primary", **kwargs.get("primary", {})),
        "backup": FakeProvider("backup", **kwargs.get("backup", {})),
    }
    roles = {role: [Route("primary", "m"), Route("backup", "m")] for role in
             ["agent", "extractor", "twin", "judge", "sim_participant"]}
    return Router(nodes, roles, Settings(health_cache_seconds=0))


@pytest.mark.asyncio
async def test_router_uses_primary_when_healthy():
    router = make_router()
    text = await router.chat_text("agent", [{"role": "user", "content": "hi"}])
    assert text
    assert router.calls[-1].node == "primary"


@pytest.mark.asyncio
async def test_router_falls_back_when_primary_down():
    router = make_router(primary={"healthy": False})
    await router.node_healthy("primary")  # an earlier failed check; the next one marks it down
    text = await router.chat_text("agent", [{"role": "user", "content": "hi"}])
    assert text
    assert router.calls[-1].node == "backup"
    # the skip is recorded so the dashboard can show why the backup answered
    assert any(c.node == "primary" and c.error == "skipped: node marked down" for c in router.calls)


@pytest.mark.asyncio
async def test_one_slow_health_check_does_not_take_a_node_down():
    router = make_router(primary={"healthy": False})  # health check fails once…
    await router.chat_text("agent", [{"role": "user", "content": "hi"}])
    assert router.calls[-1].node == "primary"  # …but the node is still tried


@pytest.mark.asyncio
async def test_missing_model_does_not_take_the_node_down():
    from attack_agent.engine.llm.base import LLMError

    router = make_router()
    router._mark_failed("primary", LLMError('HTTP 404: {"error":"model \'phi4-mini\' not found"}'))
    assert await router.node_healthy("primary")


@pytest.mark.asyncio
async def test_router_falls_back_when_primary_errors():
    router = make_router(primary={"fail": True})
    await router.chat_text("agent", [{"role": "user", "content": "hi"}])
    nodes_used = [c.node for c in router.calls]
    assert "backup" in nodes_used


@pytest.mark.asyncio
async def test_router_raises_when_all_down():
    router = make_router(primary={"healthy": False}, backup={"healthy": False})
    await router.node_healthy("primary")
    await router.node_healthy("backup")
    with pytest.raises(Exception):
        await router.chat_text("agent", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_router_records_calls_and_session_id():
    from attack_agent.engine.llm import current_session_id

    router = make_router()
    token = current_session_id.set("sess_x")
    try:
        await router.chat_json("extractor", [{"role": "user", "content": "signals?"}])
    finally:
        current_session_id.reset(token)
    assert router.calls[-1].session_id == "sess_x"
    assert router.calls[-1].kind == "json"


def test_from_config_builds_nodes_and_fallback():
    config = {
        "nodes": {"a": {"kind": "fake"}, "b": {"kind": "fake"}},
        "roles": {"agent": ["a/m1"]},
        "fallback": ["b/m2"],
    }
    # fake kind isn't in the factory, so use ollama to exercise parsing
    config["nodes"] = {"a": {"kind": "ollama", "url": "http://x"}, "b": {"kind": "ollama", "url": "http://y"}}
    router = Router.from_config(config, Settings())
    assert [str(r) for r in router.roles["agent"]] == ["a/m1", "b/m2"]
    assert router.roles["twin"] == [Route("b", "m2")]
