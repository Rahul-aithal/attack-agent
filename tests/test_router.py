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
    text = await router.chat_text("agent", [{"role": "user", "content": "hi"}])
    assert text
    assert router.calls[-1].node == "backup"


@pytest.mark.asyncio
async def test_router_falls_back_when_primary_errors():
    router = make_router(primary={"fail": True})
    await router.chat_text("agent", [{"role": "user", "content": "hi"}])
    nodes_used = [c.node for c in router.calls]
    assert "backup" in nodes_used


@pytest.mark.asyncio
async def test_router_raises_when_all_down():
    router = make_router(primary={"healthy": False}, backup={"healthy": False})
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
