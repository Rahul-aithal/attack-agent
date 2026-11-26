"""The profiling conversation ("Alex").

Question quality matters more than quantity: personality shows up in what people *do* in concrete
situations, not in how they label themselves. So Alex reacts to something specific the participant
said, then asks one open, situational question, staying on a topic for a couple of turns while it
is still informative before moving to the least-covered trait.
"""

from __future__ import annotations

import re

from attack_agent.engine.llm import RoleClient
from attack_agent.state import AgentState

TRAIT_TOPIC_HINTS = {
    "openness": "curiosity and new experiences",
    "conscientiousness": "planning, routines and deadlines",
    "extraversion": "social energy and how they spend free time",
    "agreeableness": "helping others, trust and handling disagreements",
    "neuroticism": "stress, pressure and setbacks",
}

# Angles for concrete, situational questions (examples for the model, never to be read out
# verbatim). Behaviour in a real situation is far better evidence than a self-description.
TRAIT_ANGLES = {
    "openness": [
        "something new they tried recently and what drew them to it",
        "a show, book, game or idea that changed how they think about something",
        "on a free day with no plans: somewhere familiar or somewhere new",
        "a hobby or skill they'd love to pick up and why",
    ],
    "conscientiousness": [
        "how they handled their last big deadline or exam week",
        "whether they plan trips in detail or decide on the go",
        "how they keep track of things to do (lists, apps, memory)",
        "what they do when a plan falls through at the last minute",
    ],
    "extraversion": [
        "their ideal weekend: a big group, a few close friends, or time alone",
        "how they feel after a long party or social event",
        "whether they're the one who starts conversations with new people",
        "what they did the last time they had an evening completely free",
    ],
    "agreeableness": [
        "the last time a friend asked for a favour at a bad moment",
        "how they handle a disagreement in a group project or team",
        "how quickly they tend to trust someone new",
        "what they do when someone is being unfair to someone else",
    ],
    "neuroticism": [
        "what a stressful week looked like for them recently and how they got through it",
        "how they react when something goes wrong right before a deadline",
        "what helps them switch off after a tough day",
        "whether small worries stick with them or they let things go quickly",
    ],
}

REPLY_SYSTEM_PROMPT = """You are "Alex", a friendly, curious person having a relaxed one-to-one chat.

How to write each reply:
1. React briefly and genuinely to something SPECIFIC the participant just said (a detail, not a
   generic "That's great!"). Occasionally add a short, ordinary remark about yourself so it feels
   like a two-way chat, but keep the focus on them.
2. Then ask exactly ONE open question that invites a story or an example: "what", "how",
   "tell me about a time…", "what did you do when…". Ask about real situations and what they
   actually did, not for self-labels ("are you organised?"). No yes/no questions, no two questions
   in one, no chains of "why?".
3. {length_rule}

Adapt to them:
- {engagement_rule}
- Match their tone and vocabulary. Use emojis only if they do.
- If they ask you something, answer it briefly and naturally first.
- If they seem uncomfortable or deflect, drop the topic and move on lightly.

Topic for this reply: {focus}
{angles}{asked}{note}
Never:
- mention personality, traits, profiling, analysis, research, tests or this being a study;
- give advice, therapy-style reflections, or flattery;
- ask about health or diagnoses, religion, politics, sexuality, money, or painful family matters;
- ask for identifying details (full name, address, workplace or college name, contacts);
- repeat or rephrase a question you already asked.

Write only your next message. No speaker label, no quotes."""

OPENING_PROMPT = """You are "Alex", a friendly, curious person starting a relaxed one-to-one chat.
Write a short opening message: say hi, introduce yourself as Alex in a few words, and ask ONE easy,
open question about their day or week that invites more than a one-word answer (for example what
they've been up to, or the best part of their week so far). {length_rule}
Write only the message. No speaker label, no quotes."""

_QUESTION_RE = re.compile(r"[^.!?\n]*\?")


def length_rule(device: str | None) -> str:
    if device == "mobile":
        return (
            "They are on a PHONE: keep the whole message to 1-2 short sentences (under 30 words), "
            "like a text message."
        )
    return "Keep the whole message to 1-3 sentences."


def _engagement_rule(state: AgentState) -> str:
    last = next(
        (m["content"] for m in reversed(state.conversation_history) if m["role"] == "user"), ""
    )
    words = len(last.split())
    if words <= 5:
        return (
            "Their last answer was very short: make the next question easier and more concrete "
            "(e.g. a light either/or or a 'what was the last time…' question), and keep yours short."
        )
    if words >= 40:
        return (
            "They are sharing a lot: follow up on the most interesting detail they gave before "
            "moving to anything new."
        )
    return "Follow up on what they said if it is interesting; otherwise move to the topic below."


def _questions_asked(state: AgentState, limit: int = 12) -> list[str]:
    asked: list[str] = []
    for m in state.conversation_history:
        if m["role"] == "assistant":
            asked += [q.strip() for q in _QUESTION_RE.findall(m["content"]) if len(q.strip()) > 8]
    return asked[-limit:]


class ConversationEngine:
    # stay on a still-uncertain topic for up to this many replies before moving on
    TOPIC_TURNS = 2
    CONFIDENT = 0.55

    def __init__(self, llm: RoleClient):
        self.llm = llm
        self._topic: str | None = None
        self._topic_turns = 0

    async def generate_opening(self, device: str | None = None) -> str:
        prompt = OPENING_PROMPT.format(length_rule=length_rule(device))
        return await self.llm.chat_text([{"role": "user", "content": prompt}])

    # ------------------------------------------------------------------ topic planning
    def plan_focus(self, state: AgentState) -> list[str]:
        """The trait the next reply should explore (empty = free conversation)."""
        if state.turn_count <= 1:
            return []  # first exchange: just build rapport around what they said
        estimates = state.trait_estimates
        cur = self._topic
        if (
            cur in estimates
            and estimates[cur].confidence < self.CONFIDENT
            and self._topic_turns < self.TOPIC_TURNS
        ):
            return [cur]
        uncertain = [
            (e.evidence_count > 0, e.confidence, name)
            for name, e in estimates.items()
            if e.confidence < self.CONFIDENT and name != cur
        ]
        if not uncertain:
            return []
        uncertain.sort()  # untouched traits first, then the least confident
        return [uncertain[0][2]]

    def commit_focus(self, focus: list[str]) -> None:
        """Record the topic actually used for a reply (auto or researcher-steered)."""
        topic = focus[0] if focus else None
        if topic and topic == self._topic:
            self._topic_turns += 1
        else:
            self._topic, self._topic_turns = topic, 1 if topic else 0

    # ------------------------------------------------------------------ prompting
    def _reply_messages(
        self, state: AgentState, focus: list[str] | None = None, note: str | None = None
    ) -> list[dict[str, str]]:
        focus = self.plan_focus(state) if focus is None else focus
        if focus:
            topic = "; ".join(TRAIT_TOPIC_HINTS[t] for t in focus if t in TRAIT_TOPIC_HINTS)
            angles = "Possible angles (pick one that fits the conversation; don't copy wording):\n"
            angles += "".join(f"  - {a}\n" for t in focus for a in TRAIT_ANGLES.get(t, []))
            topic += " (lead into it naturally from what they just said)"
        else:
            topic = "follow what they just said and keep the conversation flowing naturally"
            angles = ""
        asked = _questions_asked(state)
        asked_text = (
            "Questions you already asked:\n" + "".join(f"  - {q}\n" for q in asked) if asked else ""
        )
        extra = f"Additional guidance for this reply: {note}\n" if note else ""
        system = REPLY_SYSTEM_PROMPT.format(
            focus=topic,
            angles=angles,
            asked=asked_text,
            note=extra,
            length_rule=length_rule(state.device),
            engagement_rule=_engagement_rule(state),
        )
        return [{"role": "system", "content": system}] + state.conversation_history[-10:]

    async def generate_reply(
        self, state: AgentState, focus: list[str] | None = None, note: str | None = None
    ) -> str:
        return await self.llm.chat_text(self._reply_messages(state, focus, note))

    def stream_reply(
        self, state: AgentState, focus: list[str] | None = None, note: str | None = None
    ):
        """Async iterator of reply tokens (for live token streaming to a UI)."""
        return self.llm.stream(self._reply_messages(state, focus, note))
