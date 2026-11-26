"""Concrete provider adapters: Ollama, OpenAI-compatible, Anthropic, Gemini."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from attack_agent.engine.llm.base import (
    LLMError,
    Message,
    Provider,
    check_response,
    iter_sse,
    split_system,
)


class OllamaProvider(Provider):
    """Native Ollama API (``/api/chat``). Supports JSON-schema constrained output."""

    kind = "ollama"
    supports_native_json = True

    def _body(self, model: str, messages: list[Message], temperature: float, stream: bool) -> dict:
        return {
            "model": model,
            "messages": messages,
            "stream": stream,
            # Disable step-by-step "thinking" on reasoning models (qwen3, deepseek-r1, ...): it
            # adds seconds per reply on laptop GPUs and isn't needed for chat or JSON. Ignored by
            # models without a thinking mode.
            "think": False,
            "options": {"temperature": temperature},
        }

    async def chat_text(self, model: str, messages: list[Message], temperature: float) -> str:
        response = await self.client().post(
            f"{self.url}/api/chat", json=self._body(model, messages, temperature, False)
        )
        check_response(response)
        return _non_empty(response.json().get("message", {}).get("content", ""))

    async def chat_json(
        self,
        model: str,
        messages: list[Message],
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        body = self._body(model, messages, temperature, False)
        body["format"] = schema or "json"
        response = await self.client().post(f"{self.url}/api/chat", json=body)
        check_response(response)
        return _non_empty(response.json().get("message", {}).get("content", ""))

    async def stream(
        self, model: str, messages: list[Message], temperature: float
    ) -> AsyncIterator[str]:
        body = self._body(model, messages, temperature, True)
        async with self.client().stream("POST", f"{self.url}/api/chat", json=body) as response:
            if response.status_code >= 400:
                await response.aread()
                check_response(response)
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise LLMError(str(chunk["error"]))
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break

    async def list_models(self) -> list[str]:
        response = await self.client().get(f"{self.url}/api/tags")
        check_response(response)
        return [m.get("name") or m.get("model") for m in response.json().get("models", [])]

    async def _health_request(self, timeout: float) -> None:
        response = await self.client().get(f"{self.url}/api/tags", timeout=timeout)
        check_response(response)


class OpenAICompatProvider(Provider):
    """Any ``/v1/chat/completions`` endpoint: OpenAI, Groq, OpenRouter, LM Studio, vLLM,
    llama.cpp server, or Ollama's own ``/v1`` endpoint. ``url`` is the base incl. ``/v1``."""

    kind = "openai_compat"
    supports_native_json = True

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _complete(self, body: dict) -> str:
        response = await self.client().post(
            f"{self.url}/chat/completions", json=body, headers=self._headers()
        )
        check_response(response)
        choices = response.json().get("choices") or []
        if not choices:
            raise LLMError("no choices in response")
        return _non_empty(choices[0].get("message", {}).get("content") or "")

    async def chat_text(self, model: str, messages: list[Message], temperature: float) -> str:
        return await self._complete(
            {"model": model, "messages": messages, "temperature": temperature}
        )

    async def chat_json(
        self,
        model: str,
        messages: list[Message],
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            return await self._complete(body)
        except LLMError as exc:
            # Some local servers reject response_format; fall back to plain prompting.
            if "HTTP 4" not in str(exc):
                raise
            body.pop("response_format")
            return await self._complete(body)

    async def stream(
        self, model: str, messages: list[Message], temperature: float
    ) -> AsyncIterator[str]:
        body = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
        async with self.client().stream(
            "POST", f"{self.url}/chat/completions", json=body, headers=self._headers()
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                check_response(response)
            async for chunk in iter_sse(response):
                choices = chunk.get("choices") or []
                if choices:
                    token = (choices[0].get("delta") or {}).get("content")
                    if token:
                        yield token

    async def list_models(self) -> list[str]:
        response = await self.client().get(f"{self.url}/models", headers=self._headers())
        check_response(response)
        return [m.get("id") for m in response.json().get("data", [])]

    async def _health_request(self, timeout: float) -> None:
        response = await self.client().get(
            f"{self.url}/models", headers=self._headers(), timeout=timeout
        )
        check_response(response)


class AnthropicProvider(Provider):
    """Anthropic Messages API."""

    kind = "anthropic"
    max_tokens = 1024

    def __init__(self, name: str, url: str = "https://api.anthropic.com", **kwargs: Any):
        super().__init__(name, url or "https://api.anthropic.com", **kwargs)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _body(self, model: str, messages: list[Message], temperature: float) -> dict:
        system, rest = split_system(messages)
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": _merge_consecutive(rest),
        }
        if system:
            body["system"] = system
        return body

    async def chat_text(self, model: str, messages: list[Message], temperature: float) -> str:
        response = await self.client().post(
            f"{self.url}/v1/messages",
            json=self._body(model, messages, temperature),
            headers=self._headers(),
        )
        check_response(response)
        blocks = response.json().get("content") or []
        return _non_empty("".join(b.get("text", "") for b in blocks if b.get("type") == "text"))

    async def stream(
        self, model: str, messages: list[Message], temperature: float
    ) -> AsyncIterator[str]:
        body = self._body(model, messages, temperature) | {"stream": True}
        async with self.client().stream(
            "POST", f"{self.url}/v1/messages", json=body, headers=self._headers()
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                check_response(response)
            async for event in iter_sse(response):
                if event.get("type") == "content_block_delta":
                    token = (event.get("delta") or {}).get("text")
                    if token:
                        yield token

    async def list_models(self) -> list[str]:
        response = await self.client().get(f"{self.url}/v1/models", headers=self._headers())
        check_response(response)
        return [m.get("id") for m in response.json().get("data", [])]

    async def _health_request(self, timeout: float) -> None:
        response = await self.client().get(
            f"{self.url}/v1/models", headers=self._headers(), timeout=timeout
        )
        check_response(response)


class GeminiProvider(Provider):
    """Google Gemini ``generateContent`` API."""

    kind = "gemini"
    supports_native_json = True

    def __init__(
        self,
        name: str,
        url: str = "https://generativelanguage.googleapis.com/v1beta",
        **kwargs: Any,
    ):
        super().__init__(name, url or "https://generativelanguage.googleapis.com/v1beta", **kwargs)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key or "", "content-type": "application/json"}

    def _body(self, messages: list[Message], temperature: float, json_mode: bool) -> dict:
        system, rest = split_system(messages)
        contents = [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in rest
        ]
        config: dict[str, Any] = {"temperature": temperature}
        if json_mode:
            config["responseMimeType"] = "application/json"
        body: dict[str, Any] = {"contents": contents, "generationConfig": config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    @staticmethod
    def _text(payload: dict) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)

    async def _generate(self, model: str, body: dict) -> str:
        response = await self.client().post(
            f"{self.url}/models/{model}:generateContent", json=body, headers=self._headers()
        )
        check_response(response)
        return _non_empty(self._text(response.json()))

    async def chat_text(self, model: str, messages: list[Message], temperature: float) -> str:
        return await self._generate(model, self._body(messages, temperature, False))

    async def chat_json(
        self,
        model: str,
        messages: list[Message],
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        return await self._generate(model, self._body(messages, temperature, True))

    async def stream(
        self, model: str, messages: list[Message], temperature: float
    ) -> AsyncIterator[str]:
        async with self.client().stream(
            "POST",
            f"{self.url}/models/{model}:streamGenerateContent?alt=sse",
            json=self._body(messages, temperature, False),
            headers=self._headers(),
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                check_response(response)
            async for chunk in iter_sse(response):
                token = self._text(chunk)
                if token:
                    yield token

    async def list_models(self) -> list[str]:
        response = await self.client().get(f"{self.url}/models", headers=self._headers())
        check_response(response)
        return [m.get("name", "").removeprefix("models/") for m in response.json().get("models", [])]

    async def _health_request(self, timeout: float) -> None:
        response = await self.client().get(
            f"{self.url}/models", headers=self._headers(), timeout=timeout
        )
        check_response(response)


PROVIDER_KINDS: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "openai_compat": OpenAICompatProvider,
    "openai": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}

DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "ollama": "http://localhost:11434",
    "lmstudio": "http://localhost:1234/v1",
}


def make_provider(kind: str, name: str, url: str | None = None, **kwargs: Any) -> Provider:
    """Build a provider. ``kind`` may also be a vendor alias (groq, openrouter, lmstudio)."""
    alias = kind.lower()
    resolved_url = url or DEFAULT_URLS.get(alias, "")
    if alias in ("groq", "openrouter", "lmstudio"):
        alias = "openai_compat"
    cls = PROVIDER_KINDS.get(alias)
    if cls is None:
        raise ValueError(f"unknown provider kind: {kind}")
    if not resolved_url:
        raise ValueError(f"provider '{name}' ({kind}) needs a url")
    return cls(name, resolved_url, **kwargs)


def _non_empty(text: str) -> str:
    if not text or not text.strip():
        raise LLMError("empty response from model")
    return text.strip()


def _merge_consecutive(messages: list[Message]) -> list[Message]:
    """Anthropic requires alternating roles starting with user."""
    merged: list[Message] = []
    for m in messages:
        role = "assistant" if m["role"] == "assistant" else "user"
        if merged and merged[-1]["role"] == role:
            merged[-1] = {"role": role, "content": merged[-1]["content"] + "\n\n" + m["content"]}
        else:
            merged.append({"role": role, "content": m["content"]})
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "(continue)"})
    return merged
