"""Provider interface shared by every model backend."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import httpx

Message = dict[str, str]


class LLMError(Exception):
    """Raised when a provider call fails or returns nothing usable."""


_THINK_BLOCK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove reasoning blocks (<think>…</think>) that reasoning models such as qwen3 or
    deepseek-r1 emit when the server ignores `think: false` (older Ollama versions)."""
    return _THINK_BLOCK.sub("", text or "").strip() if "<think" in (text or "").lower() else (text or "")


class ThinkFilter:
    """Streaming counterpart of strip_think: drops tokens inside <think>…</think>."""

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, token: str) -> str:
        self._buf += token
        out = ""
        while self._buf:
            if self._inside:
                end = self._buf.lower().find("</think>")
                if end < 0:
                    self._buf = self._buf[-8:]  # keep a tail in case the tag is split
                    return out
                self._buf = self._buf[end + len("</think>"):].lstrip()
                self._inside = False
            else:
                start = self._buf.lower().find("<think>")
                if start < 0:
                    # hold back a possible partial "<think" at the end
                    cut = self._buf.rfind("<")
                    if cut >= 0 and "<think>".startswith(self._buf[cut:].lower()):
                        out, self._buf = out + self._buf[:cut], self._buf[cut:]
                    else:
                        out, self._buf = out + self._buf, ""
                    return out
                out += self._buf[:start]
                self._buf = self._buf[start + len("<think>"):]
                self._inside = True
        return out

    def flush(self) -> str:
        rest = "" if self._inside else self._buf
        self._buf = ""
        return rest


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply (tolerates prose and code fences)."""
    if not text:
        return None
    text = strip_think(text)
    text = re.sub(r"```(?:json)?", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    raw = match.group(0)
    for candidate in (raw, raw.replace("'", '"'), re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    """Separate system messages (Anthropic/Gemini take them as a separate field)."""
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    rest = [m for m in messages if m.get("role") != "system"]
    if not rest:
        rest = [{"role": "user", "content": system or "Hello"}]
        system = ""
    return system, rest


class Provider(ABC):
    """A single model endpoint (one machine or one cloud account)."""

    kind: str = "base"
    supports_native_json: bool = False

    def __init__(
        self,
        name: str,
        url: str,
        api_key: str | None = None,
        timeout: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.name = name
        self.url = url.rstrip("/")
        self._api_key = api_key
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def __repr__(self) -> str:  # never leak keys into logs
        key = "set" if self._api_key else "none"
        return f"<{type(self).__name__} name={self.name} url={self.url} key={key}>"

    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0), transport=self._transport
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    @abstractmethod
    async def chat_text(self, model: str, messages: list[Message], temperature: float) -> str: ...

    async def chat_json(
        self,
        model: str,
        messages: list[Message],
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        """Return raw text that should contain JSON. Adapters override to use native JSON mode."""
        return await self.chat_text(model, messages, temperature)

    @abstractmethod
    def stream(self, model: str, messages: list[Message], temperature: float) -> AsyncIterator[str]: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    async def health(self, timeout: float = 4.0) -> bool:
        try:
            await self._health_request(timeout)
            return True
        except Exception:
            return False

    @abstractmethod
    async def _health_request(self, timeout: float) -> None: ...


def check_response(response: httpx.Response) -> None:
    if response.status_code >= 400:
        body = response.text[:300]
        raise LLMError(f"HTTP {response.status_code}: {body}")


async def iter_sse(response: httpx.Response) -> AsyncIterator[dict]:
    """Yield JSON payloads from a server-sent-events stream."""
    async for line in response.aiter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue
