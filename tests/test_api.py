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
    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:  # the participant drives it
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


def test_admin_feed_pushes_sessions_and_nodes(client):
    c, _ = client
    with c.websocket_connect("/admin/stream?admin_token=tok") as feed:
        first = feed.receive_json()
        assert first == {"type": "sessions", "sessions": []}
        sid = c.post("/sessions", json={"consent": True}).json()["session_id"]
        seen_session = seen_nodes = False
        for _ in range(20):
            msg = feed.receive_json()
            if msg["type"] == "sessions" and any(s["session_id"] == sid for s in msg["sessions"]):
                seen_session = True
            if msg["type"] == "nodes":
                seen_nodes = msg["nodes"][0]["node"] == "fake"
            if seen_session and seen_nodes:
                break
        assert seen_session and seen_nodes


def test_admin_feed_rejects_bad_token(client):
    c, _ = client
    with c.websocket_connect("/admin/stream?admin_token=wrong") as feed:
        assert feed.receive_json()["type"] == "error"


def _until(ws, event_type, limit=200):
    seen = []
    for _ in range(limit):
        event = ws.receive_json()
        seen.append(event)
        if event["type"] == event_type:
            return seen
    raise AssertionError(f"no {event_type} event")


def test_join_code_resolves_and_rejoin_replays_chat(client):
    c, _ = client
    created = c.post("/sessions", json={"consent": True}).json()
    sid, code = created["session_id"], created["join_code"]
    assert len(code) == 6
    assert c.get(f"/join/{code.lower()}").json()["session_id"] == sid
    assert c.get("/join/ZZZZZZ").status_code == 404

    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:
        _until(ws, "await_message")
        ws.send_json({"kind": "message", "text": "I plan ahead and love helping people"})
        _until(ws, "await_message")
    # connection dropped mid-session; rejoin within the grace period
    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:
        replay = _until(ws, "await_message")
        replay += _until(ws, "await_message")
        types = [e["type"] for e in replay]
        assert "participant_message" in types  # own messages come back too
        assert types.count("agent_message") >= 2
    assert c.get(f"/sessions/{sid}").json()["aborted"] is False


def test_participant_who_never_returns_is_aborted(client):
    import time

    c, _ = client
    c.app.state.manager.settings.participant_grace_seconds = 0.2
    sid = c.post("/sessions", json={"consent": True}).json()["session_id"]
    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:
        _until(ws, "await_message")
    for _ in range(50):
        if c.get(f"/sessions/{sid}").json()["aborted"]:
            break
        time.sleep(0.1)
    assert c.get(f"/sessions/{sid}").json()["aborted"] is True


def test_telemetry_and_model_activity_reach_the_admin_feed(client):
    c, _ = client
    assert c.post("/telemetry", json={"name": "windows"}).status_code == 401
    with c.websocket_connect("/admin/stream?admin_token=tok") as feed:
        kinds = {feed.receive_json()["type"] for _ in range(3)}
        assert kinds == {"sessions", "machines", "llm"}
        ok = c.post("/telemetry", json={"name": "windows", "cpu_pct": 42.0},
                    headers={"X-Admin-Token": "tok"})
        assert ok.status_code == 200
        for _ in range(20):
            msg = feed.receive_json()
            if msg["type"] == "machines":
                assert msg["machines"][0]["name"] == "windows"
                assert msg["machines"][0]["cpu_pct"] == 42.0
                break
        else:
            raise AssertionError("no machines update")

        sid = c.post("/sessions", json={"consent": True}).json()["session_id"]
        saw_active = saw_done = False
        # the session (and its first model call) starts when the participant connects
        with c.websocket_connect(f"/sessions/{sid}/stream?device=mobile") as ws:
            _until(ws, "await_message")
            for _ in range(100):
                msg = feed.receive_json()
                if msg["type"] == "llm":
                    saw_active |= any(a["session_id"] == sid for a in msg["active"])
                    saw_done |= any(r["session_id"] == sid and r["latency_ms"] >= 0
                                    for r in msg["recent"])
                if saw_active and saw_done:
                    break
        assert saw_active and saw_done  # opening message: call started, then finished
        assert c.app.state.manager.get(sid).state.device == "mobile"


def test_session_list_counts_answers(client):
    c, _ = client
    sid = c.post("/sessions", json={"consent": True}).json()["session_id"]
    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:
        _until(ws, "await_message")
        ws.send_json({"kind": "message", "text": "I plan ahead and love helping people"})
        _until(ws, "await_message")
        rows = {r["session_id"]: r for r in c.app.state.manager.list_sessions()}
        assert rows[sid]["participant_messages"] == 1
        assert rows[sid]["agent_messages"] == 2  # opening + reply
        assert rows[sid]["questionnaire_total"] == 50


def _run_full_session(c):
    sid = c.post("/sessions", json={"consent": True}).json()["session_id"]
    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:
        ws.send_json({"kind": "client_info", "device": "mobile"})
        try:
            while True:
                event = ws.receive_json()
                if event["type"] == "await_message":
                    ws.send_json({"kind": "message", "text": "I plan ahead and love helping people"})
                elif event["type"] == "await_questionnaire":
                    ws.send_json({"kind": "questionnaire",
                                  "responses": {str(i): 4 for i in range(1, 51)}})
                elif event["type"] == "complete":
                    break
        except WebSocketDisconnect:
            pass
    c.app.state.manager.sessions  # noqa: B018
    return sid


def test_reports_markdown_by_default_pdf_on_request(client):
    c, _ = client
    sid = _run_full_session(c)
    import time

    for _ in range(50):  # saved by the background watcher
        if c.get(f"/sessions/{sid}/report", headers={"X-Admin-Token": "tok"}).status_code == 200:
            break
        time.sleep(0.05)
    md = c.get(f"/sessions/{sid}/report", headers={"X-Admin-Token": "tok"})
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    assert "# Session report" in md.text and "## Transcript" in md.text
    assert "| Device | mobile |" in md.text

    study = c.get("/report", headers={"X-Admin-Token": "tok"})
    assert study.status_code == 200 and "# Study report" in study.text

    pdf = c.get(f"/sessions/{sid}/report?format=pdf", headers={"X-Admin-Token": "tok"})
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"
    assert c.get(f"/sessions/{sid}/report").status_code == 401


def test_newer_participant_connection_replaces_older(client):
    c, _ = client
    sid = c.post("/sessions", json={"consent": True}).json()["session_id"]
    with c.websocket_connect(f"/sessions/{sid}/stream") as first:
        _until(first, "await_message")
        with c.websocket_connect(f"/sessions/{sid}/stream") as second:
            _until(first, "replaced")
            _until(second, "await_message")  # history replayed to the new device
            second.send_json({"kind": "message", "text": "hello from my phone"})
            _until(second, "participant_message")


def test_dashboard_does_not_start_a_session(client):
    c, _ = client
    sid = c.post("/sessions", json={"consent": True}).json()["session_id"]
    with c.websocket_connect(f"/sessions/{sid}/stream?admin_token=tok"):
        pass
    row = next(r for r in c.app.state.manager.list_sessions() if r["session_id"] == sid)
    assert row["phase"] == "waiting"


def _restart_server(c, settings):
    """Simulate a server restart: a brand-new manager with the same output dir / database."""
    node = FakeProvider("fake")
    roles = {r: [Route("fake", "m")] for r in
             ["agent", "extractor", "twin", "judge", "sim_participant"]}
    c.app.state.manager = SessionManager(settings, router=Router({"fake": node}, roles, settings))


def test_rejoin_with_code_after_server_restart_continues_the_chat(client):
    c, settings = client
    created = c.post("/sessions", json={"consent": True}).json()
    sid, code = created["session_id"], created["join_code"]
    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:
        _until(ws, "await_message")
        ws.send_json({"kind": "message", "text": "I love planning trips with friends"})
        _until(ws, "await_message")

    _restart_server(c, settings)  # everything in memory is gone

    joined = c.get(f"/join/{code}").json()
    assert joined["session_id"] == sid and not joined["finished"] and joined["resumed"]
    with c.websocket_connect(f"/sessions/{sid}/stream") as ws:
        replay = _until(ws, "await_message")
        texts = [e.get("text") for e in replay if e["type"] == "participant_message"]
        assert "I love planning trips with friends" in texts  # earlier chat restored
        assert any(e["type"] == "resumed" for e in replay)
        ws.send_json({"kind": "message", "text": "and I keep a strict calendar"})
        _until(ws, "participant_message")
    state = c.app.state.manager.get(sid).state
    assert state.turn_count >= 1  # carried on from the saved turn count


def test_timed_out_participant_can_rejoin_but_one_who_left_cannot(client):
    import time

    c, _ = client
    c.app.state.manager.settings.participant_grace_seconds = 0.1
    a = c.post("/sessions", json={"consent": True}).json()
    with c.websocket_connect(f"/sessions/{a['session_id']}/stream") as ws:
        _until(ws, "await_message")  # then the connection drops…
    for _ in range(50):
        if c.app.state.manager.get(a["session_id"]).state.aborted:
            break
        time.sleep(0.05)
    again = c.get(f"/join/{a['join_code']}").json()
    assert not again["finished"]  # timed out → reopened
    assert not c.app.state.manager.get(a["session_id"]).state.aborted

    b = c.post("/sessions", json={"consent": True}).json()
    with c.websocket_connect(f"/sessions/{b['session_id']}/stream") as ws:
        _until(ws, "await_message")
        ws.send_json({"kind": "abort"})  # "Leave study"
        _until(ws, "aborted")
    left = c.get(f"/join/{b['join_code']}").json()
    assert left["finished"] and left["reason"] == "left"
    # …but the researcher can reopen it
    r = c.post(f"/sessions/{b['session_id']}/reopen", headers={"X-Admin-Token": "tok"})
    assert r.status_code == 200 and not c.app.state.manager.get(b["session_id"]).state.aborted


def test_history_lists_previous_sessions_after_restart(client):
    c, settings = client
    created = c.post("/sessions", json={"consent": True}).json()
    with c.websocket_connect(f"/sessions/{created['session_id']}/stream") as ws:
        _until(ws, "await_message")
    _restart_server(c, settings)
    assert c.get("/sessions/history").status_code == 401
    rows = c.get("/sessions/history", headers={"X-Admin-Token": "tok"}).json()["sessions"]
    row = next(r for r in rows if r["session_id"] == created["session_id"])
    assert row["join_code"] == created["join_code"]
    assert row["status"] in ("interrupted", "aborted") and row["resumable"]
