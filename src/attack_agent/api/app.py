"""FastAPI application.

Participant endpoints (start a session, chat over WebSocket, submit the questionnaire) are open
when ``public_sessions`` is true. Researcher/presenter endpoints (live profile, nodes, routing,
BYOK, experiments, exports) require the admin token via the ``X-Admin-Token`` header or
``?admin_token=`` query parameter. Participant-facing streams never carry live trait data.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger
from pydantic import BaseModel

from attack_agent.api.manager import SessionManager
from attack_agent.config import get_settings
from attack_agent.engine.llm import ROLES
from attack_agent.engine.questionnaire import questionnaire_items
from attack_agent.storage import (
    delete_participant_data,
    delete_session,
    export_session,
    export_sessions_csv,
)


class CreateSessionRequest(BaseModel):
    participant_id: str | None = None
    experiment_id: str | None = None
    consent: bool = True
    config: dict | None = None


class QuestionnaireRequest(BaseModel):
    responses: dict[int, int]


class RoutingRequest(BaseModel):
    role: str
    routes: list[str]


class BYOKRequest(BaseModel):
    name: str
    kind: str
    url: str | None = None
    api_key: str | None = None


class ExperimentRequest(BaseModel):
    name: str
    config: dict | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.manager = SessionManager(settings)
    logger.info("admin token: {}", app.state.manager.admin_token)
    try:
        yield
    finally:
        await app.state.manager.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Attack Agent API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def manager(ws_or_req=None) -> SessionManager:
        return app.state.manager

    def require_admin(
        x_admin_token: str | None = Header(default=None),
        admin_token: str | None = Query(default=None),
    ) -> bool:
        token = x_admin_token or admin_token
        if token != app.state.manager.admin_token:
            raise HTTPException(status_code=401, detail="admin token required")
        return True

    def is_admin_token(token: str | None) -> bool:
        return bool(token) and token == app.state.manager.admin_token

    # -------------------------------------------------------------- meta
    @app.get("/health")
    async def health():
        return {"status": "ok", "roles": list(ROLES)}

    @app.get("/questionnaire")
    async def get_questionnaire():
        return {"items": questionnaire_items()}

    # -------------------------------------------------------------- sessions
    @app.post("/sessions")
    async def create_session(req: CreateSessionRequest):
        if not get_settings().public_sessions:
            raise HTTPException(status_code=403, detail="public sessions disabled")
        if not req.consent:
            raise HTTPException(status_code=400, detail="consent is required to start a session")
        engine = app.state.manager.create_session(
            req.participant_id, req.experiment_id, req.config
        )
        return {"session_id": engine.session_id}

    @app.get("/sessions/{session_id}")
    async def get_session(
        session_id: str,
        x_admin_token: str | None = Header(default=None),
        admin_token: str | None = Query(default=None),
    ):
        include = is_admin_token(x_admin_token or admin_token)
        summary = app.state.manager.session_summary(session_id, include_profile=include)
        if summary is None:
            raise HTTPException(status_code=404, detail="session not found")
        return summary

    @app.post("/sessions/{session_id}/questionnaire")
    async def submit_questionnaire(session_id: str, req: QuestionnaireRequest):
        engine = app.state.manager.get(session_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="session not found")
        engine.submit_questionnaire(req.responses)
        return {"status": "accepted"}

    @app.post("/sessions/{session_id}/abort")
    async def abort_session(session_id: str):
        engine = app.state.manager.get(session_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="session not found")
        engine.abort()
        return {"status": "aborting"}

    @app.get("/sessions/{session_id}/export", dependencies=[Depends(require_admin)])
    async def export(session_id: str):
        data = export_session(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="session not persisted yet")
        return data

    @app.delete("/sessions/{session_id}", dependencies=[Depends(require_admin)])
    async def delete(session_id: str):
        app.state.manager.sessions.pop(session_id, None)
        removed = delete_session(session_id)
        return {"deleted": removed}

    @app.delete("/participants/{participant_id}", dependencies=[Depends(require_admin)])
    async def delete_participant(participant_id: str):
        n = delete_participant_data(participant_id)
        return {"deleted_sessions": n}

    # -------------------------------------------------------------- researcher data
    @app.get("/export.csv", dependencies=[Depends(require_admin)])
    async def export_csv():
        return PlainTextResponse(export_sessions_csv(), media_type="text/csv")

    @app.get("/nodes", dependencies=[Depends(require_admin)])
    async def nodes():
        return {"nodes": await app.state.manager.nodes_status()}

    @app.put("/routing", dependencies=[Depends(require_admin)])
    async def routing(req: RoutingRequest):
        if req.role not in ROLES:
            raise HTTPException(status_code=400, detail=f"unknown role; choose from {list(ROLES)}")
        app.state.manager.set_routing(req.role, req.routes)
        return {"status": "updated", "role": req.role}

    @app.post("/byok", dependencies=[Depends(require_admin)])
    async def byok(req: BYOKRequest):
        app.state.manager.add_byok(req.name, req.kind, req.url, req.api_key)
        return {"status": "added", "node": req.name}

    @app.get("/experiments", dependencies=[Depends(require_admin)])
    async def list_experiments():
        return {
            "experiments": [
                {"id": e.id, "name": e.name, "sessions": len(e.session_ids), "config": e.config}
                for e in app.state.manager.experiments.values()
            ]
        }

    @app.post("/experiments", dependencies=[Depends(require_admin)])
    async def create_experiment(req: ExperimentRequest):
        exp = app.state.manager.create_experiment(req.name, req.config)
        return {"id": exp.id, "name": exp.name}

    # -------------------------------------------------------------- websocket
    @app.websocket("/sessions/{session_id}/stream")
    async def stream(websocket: WebSocket, session_id: str):
        await websocket.accept()
        mgr: SessionManager = app.state.manager
        engine = mgr.get(session_id)
        if engine is None:
            await websocket.send_json({"type": "error", "message": "session not found"})
            await websocket.close()
            return
        token = websocket.query_params.get("admin_token")
        include_profile = is_admin_token(token)

        async def pump_input():
            try:
                while True:
                    data = await websocket.receive_json()
                    kind = data.get("kind") or data.get("type")
                    if kind == "message":
                        engine.submit_message(str(data.get("text", "")))
                    elif kind == "questionnaire":
                        engine.submit_questionnaire(data.get("responses", {}))
                    elif kind == "abort":
                        engine.abort()
            except WebSocketDisconnect:
                engine.abort()
            except Exception as exc:  # pragma: no cover
                logger.debug("ws input pump ended: {}", exc)

        input_task = asyncio.create_task(pump_input())
        try:
            async for event in engine.events():
                shaped = mgr.filter_event(event, include_profile)
                if shaped is not None:
                    await websocket.send_json(shaped)
            await mgr.persist(session_id)
        except WebSocketDisconnect:
            pass
        finally:
            input_task.cancel()
            try:
                await websocket.close()
            except Exception:
                pass

    # -------------------------------------------------------------- static web UI
    dist = Path(settings.web_dist)
    if dist.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
    else:

        @app.get("/")
        async def root():
            return JSONResponse(
                {
                    "service": "attack-agent",
                    "docs": "/docs",
                    "note": "web UI not built; run `bun run build` in web/ or use the CLI",
                }
            )

    return app


app = create_app()
