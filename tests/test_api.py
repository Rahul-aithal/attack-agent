"""API + WebSocket integration test driven by a fake model node (no server needed)."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from attack_agent.api.app import create_app
from attack_agent.api.manager import SessionManager
from attack_agent.engine.llm import Route, Router
from tests.fakes import FakeProvider


@pytest.fixture
def client(tmp_path, monkeypatch):
    from attack_agent.config import get_settings

    monkeypatch.setenv("ATTACK_AGENT_MIN_TURNS", "2")
    monkeypatch.setenv("ATTACK_AGENT_MAX_TURNS", "3")
    monkeypatch.setenv("ATTACK_AGENT_HEALTH_CACHE_SECONDS", "0")
    monkeypatch.setenv("ATTACK_AGENT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("ATTACK_AGENT_DATABASE_URL", f"sqlite:///{tmp_path}/api.db")
    monkeypatch.setenv("ATTACK_AGENT_ADMIN_TOKEN", "tok")
    monkeypatch.setenv("ATTACK_AGENT_PUBLIC_SESSIONS", "true")
    monkeypatch.setenv("ATTACK_AGENT_WEB_DIST", str(tmp_path / "nope"))
    get_settings.cache_clear()
    settings = get_settings()

    node = FakeProvider("fake")
    roles = {r: [Route("fake", "m")] for r in
             ["agent", "extractor", "twin", "judge", "sim_participant"]}
    router = Router({"fake": node}, roles, settings)

    app = create_app()
    with TestClient(app) as c:
        c.app.state.manager = SessionManager(settings, router=router)
        yield c, settings
    get_settings.cache_clear()


def test_health(client):
    c, _ = client
    assert c.get("/health").json()["status"] == "ok"


def test_nodes_requires_admin(client):
    c, _ = client
    assert c.get("/nodes").status_code == 401
    ok = c.get("/nodes", headers={"X-Admin-Token": "tok"})
    assert ok.status_code == 200
    assert ok.json()["nodes"][0]["node"] == "fake"


def test_full_session_over_websocket(client):
    c, _ = client
    sid = c.post("/sessions", json={"consent": True}).json()["session_id"]

    phases = []
    with c.websocket_connect(f"/sessions/{sid}/stream?admin_token=tok") as ws:
        try:
            while True:
                event = ws.receive_json()
                t = event["type"]
                if t == "phase_change":
                    phases.append(event["phase"])
                elif t == "await_message":
                    ws.send_json({"kind": "message", "text": "I plan ahead and love helping people"})
                elif t == "await_questionnaire":
                    ws.send_json({"kind": "questionnaire", "responses": {str(i): 4 for i in range(1, 51)}})
        except WebSocketDisconnect:
            pass  # server closes after persisting the finished session

    assert "complete" in phases
    # researcher stream (with token) saw profile events; export now available
    export = c.get(f"/sessions/{sid}/export", headers={"X-Admin-Token": "tok"})
    assert export.status_code == 200
    assert export.json()["session"]["id"] == sid


def test_participant_stream_hides_profile(client):
    c, _ = client
    sid = c.post("/sessions", json={"consent": True}).json()["session_id"]
    saw_profile = False
    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:  # no token
        try:
            while True:
                event = ws.receive_json()
                t = event["type"]
                if t in ("profile", "trait_update", "twin_prediction"):
                    saw_profile = True
                if t == "await_message":
                    ws.send_json({"kind": "message", "text": "hello there friend"})
                elif t == "await_questionnaire":
                    ws.send_json({"kind": "questionnaire", "responses": {}})
        except WebSocketDisconnect:
            pass
    assert not saw_profile
