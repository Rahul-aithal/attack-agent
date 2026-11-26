"""LLM provider/routing layer.

``Router`` dispatches each *role* to a node+model with a health-checked fallback chain.
``RoleClient`` binds a router to one role and exposes the ``chat_text`` / ``chat_json`` /
``stream`` surface the engine modules expect, so an engine never needs to know which machine or
model backs its role. Tests can inject any object with the same three async methods.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from attack_agent.engine.llm.base import LLMError, Message, Provider, extract_json
from attack_agent.engine.llm.providers import (
    AnthropicProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAICompatProvider,
    make_provider,
)
from attack_agent.engine.llm.router import (
    ROLES,
    LLMCallRecord,
    Route,
    Router,
    RoutingError,
    current_session_id,
)


class RoleClient:
    """A router bound to a single role."""

    def __init__(self, router: Router, role: str):
        if role not in ROLES:
            raise ValueError(f"unknown role: {role}")
        self.router = router
        self.role = role

    async def chat_text(
        self, messages: list[Message], temperature: float | None = None
    ) -> str:
        return await self.router.chat_text(self.role, messages, temperature)

    async def chat_json(
        self,
        messages: list[Message],
        temperature: float | None = None,
        schema: dict[str, Any] | None = None,
    ) -> dict | None:
        return await self.router.chat_json(self.role, messages, temperature, schema)

    def stream(
        self, messages: list[Message], temperature: float | None = None
    ) -> AsyncIterator[str]:
        return self.router.stream(self.role, messages, temperature)


__all__ = [
    "LLMError",
    "LLMCallRecord",
    "Message",
    "Provider",
    "Route",
    "Router",
    "RoutingError",
    "RoleClient",
    "ROLES",
    "OllamaProvider",
    "OpenAICompatProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "make_provider",
    "extract_json",
    "current_session_id",
]
