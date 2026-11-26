"""Role -> (node, model) routing with health checks and a fallback chain.

Roles: ``agent`` (conversation + scenario actor), ``extractor`` (signal extraction), ``twin``
(digital twin persona), ``judge`` (outcome classification), ``sim_participant`` (synthetic
participants for evaluation).

Routing comes from ``deploy.yaml`` (see ``deploy.example.yaml``). Each role lists routes in
priority order as ``node/model``; a global ``fallback`` list is appended to every role. If a node
is unreachable (failed health check or failed call) the next route is tried.
"""

from __future__ import annotations

import contextvars
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from attack_agent.config import Settings, get_settings
from attack_agent.engine.llm.base import LLMError, Message, Provider, extract_json
from attack_agent.engine.llm.providers import make_provider

ROLES = ("agent", "extractor", "twin", "judge", "sim_participant")

current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_session_id", default=None
)


@dataclass
class Route:
    node: str
    model: str

    @classmethod
    def parse(cls, value: Any) -> Route:
        if isinstance(value, dict):
            return cls(node=str(value["node"]), model=str(value["model"]))
        node, _, model = str(value).partition("/")
        if not model:
            raise ValueError(f"route '{value}' must look like node/model")
        return cls(node=node.strip(), model=model.strip())

    def __str__(self) -> str:
        return f"{self.node}/{self.model}"


@dataclass
class LLMCallRecord:
    role: str
    node: str
    model: str
    kind: str  # text | json | stream
    latency_ms: float
    ok: bool
    parse_ok: bool | None = None
    error: str | None = None
    session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


class RoutingError(LLMError):
    """No route for a role could be reached."""


class Router:
    def __init__(
        self,
        nodes: dict[str, Provider],
        roles: dict[str, list[Route]],
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.nodes = nodes
        self.roles = {role: list(roles.get(role, [])) for role in ROLES}
        self._health: dict[str, tuple[bool, float]] = {}
        self.calls: list[LLMCallRecord] = []
        self._sinks: list[Callable[[LLMCallRecord], None]] = []

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Router:
        settings = settings or get_settings()
        path = Path(settings.deploy_file)
        if path.exists():
            config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            logger.info("loading routing from {}", path)
            return cls.from_config(config, settings)
        default = make_provider(
            "ollama", "local", settings.ollama_host, timeout=settings.request_timeout
        )
        route = Route("local", settings.model_name)
        return cls({"local": default}, {role: [route] for role in ROLES}, settings)

    @classmethod
    def from_config(cls, config: dict, settings: Settings | None = None) -> Router:
        settings = settings or get_settings()
        nodes: dict[str, Provider] = {}
        for name, spec in (config.get("nodes") or {}).items():
            spec = spec or {}
            key = spec.get("api_key")
            if spec.get("api_key_env"):
                key = os.environ.get(spec["api_key_env"]) or key
                if not key:
                    logger.warning(
                        "node '{}' expects env var {} but it is unset", name, spec["api_key_env"]
                    )
            nodes[name] = make_provider(
                spec.get("kind", "ollama"),
                name,
                spec.get("url"),
                api_key=key,
                timeout=float(spec.get("timeout", settings.request_timeout)),
            )
        fallback = [Route.parse(r) for r in (config.get("fallback") or [])]
        roles_cfg = config.get("roles") or {}
        roles: dict[str, list[Route]] = {}
        for role in ROLES:
            raw = roles_cfg.get(role) or []
            routes = [Route.parse(r) for r in raw] + fallback
            # keep only routes whose node is defined
            routes = [r for r in routes if r.node in nodes]
            roles[role] = routes
        missing = [role for role in ROLES if not roles[role]]
        if missing:
            logger.warning("roles with no usable route: {}", missing)
        return cls(nodes, roles, settings)

    # ------------------------------------------------------------------ BYOK
    def add_node(
        self, name: str, kind: str, url: str | None = None, api_key: str | None = None
    ) -> None:
        """Register (or replace) a node at runtime, e.g. a user-supplied BYOK key."""
        self.nodes[name] = make_provider(
            kind, name, url, api_key=api_key, timeout=self.settings.request_timeout
        )
        self._health.pop(name, None)

    def set_route(self, role: str, routes: list[Route]) -> None:
        if role not in ROLES:
            raise ValueError(f"unknown role: {role}")
        self.roles[role] = [r for r in routes if r.node in self.nodes]

    def on_call(self, sink: Callable[[LLMCallRecord], None]) -> None:
        self._sinks.append(sink)

    # ------------------------------------------------------------------ health
    async def node_healthy(self, node: str, force: bool = False) -> bool:
        provider = self.nodes.get(node)
        if provider is None:
            return False
        cached = self._health.get(node)
        now = time.monotonic()
        if cached and not force and now - cached[1] < self.settings.health_cache_seconds:
            return cached[0]
        ok = await provider.health(timeout=self.settings.health_timeout)
        self._health[node] = (ok, now)
        return ok

    async def status(self) -> list[dict]:
        out = []
        for name, provider in self.nodes.items():
            ok = await self.node_healthy(name, force=True)
            out.append(
                {
                    "node": name,
                    "kind": provider.kind,
                    "url": provider.url,
                    "has_key": provider.has_key,
                    "healthy": ok,
                }
            )
        return out

    # ------------------------------------------------------------------ dispatch
    def _routes(self, role: str) -> list[Route]:
        routes = self.roles.get(role) or []
        if not routes:
            raise RoutingError(f"no route configured for role '{role}'")
        return routes

    def _record(
        self, role: str, route: Route, kind: str, start: float, ok: bool, parse_ok, error
    ) -> None:
        record = LLMCallRecord(
            role=role,
            node=route.node,
            model=route.model,
            kind=kind,
            latency_ms=round((time.monotonic() - start) * 1000, 1),
            ok=ok,
            parse_ok=parse_ok,
            error=error,
            session_id=current_session_id.get(),
        )
        self.calls.append(record)
        for sink in self._sinks:
            try:
                sink(record)
            except Exception as exc:  # logging must never break a call
                logger.debug("llm_call sink failed: {}", exc)

    async def chat_text(
        self, role: str, messages: list[Message], temperature: float | None = None
    ) -> str:
        temp = self.settings.temperature if temperature is None else temperature
        last_error: Exception | None = None
        for route in self._routes(role):
            if not await self.node_healthy(route.node):
                continue
            provider = self.nodes[route.node]
            start = time.monotonic()
            try:
                text = await provider.chat_text(route.model, messages, temp)
                self._record(role, route, "text", start, True, None, None)
                return text
            except Exception as exc:
                last_error = exc
                self._health[route.node] = (False, time.monotonic())
                self._record(role, route, "text", start, False, None, str(exc)[:200])
                logger.warning("route {} failed for role {}: {}", route, role, exc)
        raise RoutingError(f"all routes failed for role '{role}': {last_error}")

    async def chat_json(
        self,
        role: str,
        messages: list[Message],
        temperature: float | None = None,
        schema: dict[str, Any] | None = None,
    ) -> dict | None:
        temp = self.settings.analysis_temperature if temperature is None else temperature
        last_error: Exception | None = None
        for route in self._routes(role):
            if not await self.node_healthy(route.node):
                continue
            provider = self.nodes[route.node]
            start = time.monotonic()
            try:
                raw = await provider.chat_json(route.model, messages, temp, schema)
            except Exception as exc:
                last_error = exc
                self._health[route.node] = (False, time.monotonic())
                self._record(role, route, "json", start, False, None, str(exc)[:200])
                continue
            data = extract_json(raw)
            if data is None:
                data = await self._repair_json(provider, route, messages, raw, temp)
            self._record(role, route, "json", start, True, data is not None, None)
            return data
        raise RoutingError(f"all routes failed for role '{role}': {last_error}")

    async def _repair_json(
        self, provider: Provider, route: Route, messages, raw: str, temp: float
    ) -> dict | None:
        data = None
        for _ in range(max(0, self.settings.json_repair_retries)):
            repair = [
                *messages,
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Respond with ONLY the corrected valid JSON object."},
            ]
            try:
                raw = await provider.chat_text(route.model, repair, temp)
            except Exception:
                break
            data = extract_json(raw)
            if data is not None:
                break
        return data

    async def stream(
        self, role: str, messages: list[Message], temperature: float | None = None
    ) -> AsyncIterator[str]:
        temp = self.settings.temperature if temperature is None else temperature
        last_error: Exception | None = None
        for route in self._routes(role):
            if not await self.node_healthy(route.node):
                continue
            provider = self.nodes[route.node]
            start = time.monotonic()
            produced = False
            try:
                async for token in provider.stream(route.model, messages, temp):
                    produced = True
                    yield token
                self._record(role, route, "stream", start, True, None, None)
                return
            except Exception as exc:
                last_error = exc
                self._record(role, route, "stream", start, False, None, str(exc)[:200])
                if produced:
                    # already emitted tokens downstream; cannot safely retry another route
                    raise
                self._health[route.node] = (False, time.monotonic())
                logger.warning("stream route {} failed for role {}: {}", route, role, exc)
        raise RoutingError(f"all stream routes failed for role '{role}': {last_error}")

    async def list_models(self, node: str | None = None) -> dict[str, list[str]]:
        targets = [node] if node else list(self.nodes)
        out: dict[str, list[str]] = {}
        for name in targets:
            provider = self.nodes.get(name)
            if provider is None:
                continue
            try:
                out[name] = await provider.list_models()
            except Exception as exc:
                logger.debug("list_models failed for {}: {}", name, exc)
                out[name] = []
        return out

    async def aclose(self) -> None:
        for provider in self.nodes.values():
            await provider.aclose()
