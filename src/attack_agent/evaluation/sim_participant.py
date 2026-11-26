"""A synthetic participant: the ``sim_participant`` role plays a persona, replying to the agent's
messages and answering the self-report questionnaire in character."""

from __future__ import annotations

import json
import re

from loguru import logger

from attack_agent.data.ipip50 import IPIP50
from attack_agent.engine.llm import RoleClient, extract_json
from attack_agent.evaluation.personas import Persona

REPLY_PROMPT = """You are role-playing this person in a casual chat. Stay fully in character.

PERSON (Big Five tendencies):
{traits}
Character notes: {blurb}

Conversation so far:
{history}

Write this person's next chat reply in their voice (1-3 sentences, natural, no narration).
Reply with the message only."""

QUESTIONNAIRE_PROMPT = """You are this person answering a personality questionnaire honestly in
character. Rate how accurately each statement describes you on a scale of 1-5
(1=very inaccurate, 5=very accurate).

PERSON (Big Five tendencies):
{traits}
Character notes: {blurb}

STATEMENTS (each begins "I ..."):
{items}

Respond with ONLY a JSON object mapping each statement id (as a string) to an integer 1-5, e.g.
{{"1": 4, "2": 2, ...}}. Include all ids."""


class SimParticipant:
    def __init__(self, llm: RoleClient, persona: Persona):
        self.llm = llm
        self.persona = persona

    async def reply(self, history: list[dict[str, str]]) -> str:
        history_text = "\n".join(
            f"{'Me' if m['role'] == 'user' else 'Alex'}: {m['content']}" for m in history[-10:]
        )
        prompt = REPLY_PROMPT.format(
            traits=self.persona.trait_lines(),
            blurb=self.persona.blurb,
            history=history_text or "(just started)",
        )
        return await self.llm.chat_text([{"role": "user", "content": prompt}])

    async def answer_questionnaire(self) -> dict[int, int]:
        items = "\n".join(f"{i.id}. I {i.text}" for i in IPIP50)
        prompt = QUESTIONNAIRE_PROMPT.format(
            traits=self.persona.trait_lines(), blurb=self.persona.blurb, items=items
        )
        try:
            raw = await self.llm.chat_json([{"role": "user", "content": prompt}])
        except Exception as exc:
            logger.warning("sim questionnaire failed: {}", exc)
            raw = None
        return self._coerce(raw)

    def _coerce(self, raw) -> dict[int, int]:
        if not isinstance(raw, dict):
            raw = extract_json(json.dumps(raw)) if raw else None
        responses: dict[int, int] = {}
        for item in IPIP50:
            value = None
            if isinstance(raw, dict):
                value = raw.get(str(item.id), raw.get(item.id))
            try:
                responses[item.id] = max(1, min(5, int(re.sub(r"[^0-9]", "", str(value)) or 3)))
            except (TypeError, ValueError):
                responses[item.id] = 3  # neutral fallback
        return responses
