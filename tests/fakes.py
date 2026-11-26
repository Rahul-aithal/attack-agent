"""In-memory fake provider so the full pipeline can run without any model server."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from attack_agent.engine.llm.base import Message, Provider


class FakeProvider(Provider):
    """Returns canned responses keyed on prompt content. ``healthy`` toggles health for fallback
    tests; ``fail`` makes every call raise."""

    kind = "fake"
    supports_native_json = True

    def __init__(self, name: str = "fake", healthy: bool = True, fail: bool = False):
        super().__init__(name, "http://fake")
        self._healthy = healthy
        self.fail = fail
        self.calls = 0

    async def chat_text(self, model: str, messages: list[Message], temperature: float) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("fake failure")
        prompt = " ".join(m["content"] for m in messages).lower()
        if "short opening message" in prompt:
            return "Hey! How's your day going so far?"
        if "classify the reply" in prompt or "respond with only this json" in prompt and "outcome" in prompt:
            return json.dumps({"outcome": "PARTIAL", "confidence": 0.6, "reasoning": "hesitant"})
        if "reply to this message exactly" in prompt:
            return "Hmm, who is this exactly? I'd like to verify first."
        if "follow-up" in prompt or "reiterates the request" in prompt:
            return "Just checking back — could you confirm your asset ID when you get a moment?"
        if "fictional actor would send" in prompt or "harmless task" in prompt:
            if '("alex")' in prompt:  # delivered by the chat agent itself
                return (
                    "By the way, I'm helping with the routine device check for our team this week — "
                    "could you open our verification portal at portal.simulated-link.example.com "
                    "and reply with your laptop's asset ID? Thanks!"
                )
            return (
                "Hi, this is Chris from IT Support — I'm running the routine device check for your "
                "team today. Could you open our verification portal at "
                "portal.simulated-link.example.com and reply with your laptop's asset ID? Thanks!"
            )
        return "That's interesting! Tell me more about what you enjoy doing."

    async def chat_json(self, model, messages, temperature, schema=None) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("fake failure")
        prompt = " ".join(m["content"] for m in messages).lower()
        if "outcome" in prompt and "resistance_signals" in prompt:
            return json.dumps(
                {"outcome": "PARTIAL", "confidence": 0.6, "rationale": "asked to verify",
                 "resistance_signals": []}
            )
        if "outcome" in prompt:
            return json.dumps({"outcome": "PARTIAL", "confidence": 0.6, "reasoning": "hesitant"})
        if "questionnaire" in prompt or "statement id" in prompt:
            return json.dumps({str(i): 3 for i in range(1, 51)})
        # signal extraction
        return json.dumps(
            {
                "signals": [
                    {"trait": "conscientiousness", "signal": "plans ahead", "direction": "high",
                     "evidence_strength": 0.7, "interpretation": "mentions planning"},
                    {"trait": "agreeableness", "signal": "wants to help", "direction": "high",
                     "evidence_strength": 0.6, "interpretation": "cooperative"},
                ],
                "tone": "friendly",
                "engagement": 0.6,
                "resistance": [],
            }
        )

    async def stream(self, model, messages, temperature) -> AsyncIterator[str]:
        text = await self.chat_text(model, messages, temperature)
        for word in text.split():
            yield word + " "

    async def list_models(self) -> list[str]:
        return ["fake-model"]

    async def _health_request(self, timeout: float) -> None:
        if not self._healthy:
            raise RuntimeError("unhealthy")
