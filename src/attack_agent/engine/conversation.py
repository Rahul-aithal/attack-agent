from attack_agent.engine.llm import LLMClient
from attack_agent.state import AgentState

TRAIT_TOPIC_HINTS = {
    "openness": "hobbies, learning new things, trying new experiences, curiosity",
    "conscientiousness": "planning, routines, organization, handling deadlines and details",
    "extraversion": "social life, teamwork, group activities, how they spend free time",
    "agreeableness": "helping others, trust in people, handling disagreements, cooperation",
    "neuroticism": "stressful situations, pressure, how they react when things go wrong",
}

REPLY_SYSTEM_PROMPT = """You are "Alex", a friendly conversational partner in a research chat study.
Have a natural, warm, casual conversation with the participant.

Rules:
- NEVER mention personality, traits, profiling, analysis, tests, or the study mechanics.
- Ask at most ONE question per reply.
- Keep replies SHORT: 1-3 sentences.
- Adapt your tone and vocabulary to the participant's style.
- Do not repeat questions you already asked.
- This turn, naturally steer the topic toward: {focus}

Conversation so far:
{history}

Write your next message only. No quotes, no labels."""

OPENING_PROMPT = """You are "Alex", a friendly conversational partner in a casual chat.
Write a short, warm opening message (1-2 sentences) greeting the participant and starting
a light conversation (e.g., how their day is going). No quotes, no labels."""


class ConversationEngine:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def generate_opening(self) -> str:
        return await self.llm.chat_text([{"role": "user", "content": OPENING_PROMPT}])

    def _focus_traits(self, state: AgentState) -> list[str]:
        uncertain = [
            (estimate.confidence, name)
            for name, estimate in state.trait_estimates.items()
            if estimate.confidence < 0.55
        ]
        uncertain.sort()
        focus = [name for _, name in uncertain[:2]]
        return focus

    async def generate_reply(self, state: AgentState) -> str:
        focus = self._focus_traits(state)
        hints = "; ".join(TRAIT_TOPIC_HINTS[t] for t in focus) if focus else (
            "whatever keeps the conversation flowing naturally"
        )
        history_text = "\n".join(
            f"{'Participant' if m['role'] == 'user' else 'Alex'}: {m['content']}"
            for m in state.conversation_history[-10:]
        )
        system = REPLY_SYSTEM_PROMPT.format(
            focus=hints,
            history=history_text or "(conversation just started)",
        )
        messages = [{"role": "system", "content": system}] + state.conversation_history[-10:]
        return await self.llm.chat_text(messages)
