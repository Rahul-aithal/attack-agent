"""The profiling conversation ("Alex").

Alex plays the friendly new one around here — light, curious, still finding their feet — and the
chat should read as a conversation between people, not an interview. Questions span everyday
personal territory (free time, friendships, feelings, small habits) as well as work and study:
personality shows up in what people *do* in concrete situations, not in how they label themselves.
So Alex reacts to something specific the participant said, then asks one open, situational
question, staying on a topic for a couple of turns while it is still informative before moving to
the least-covered trait.
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
# The bank deliberately mixes everyday-work and everyday-personal territory: personality shows
# up as much in free time, friendships and feelings as in how someone works.
TRAIT_ANGLES = {
    "openness": [
        "something new they tried recently and what drew them to it",
        "a show, book, game or idea that changed how they think about something",
        "on a free day with no plans: somewhere familiar or somewhere new",
        "a hobby or skill they'd love to pick up and why",
        "the last time they changed something about themselves just to see how it felt",
        "whether their head is usually full of daydreams and ideas or quiet and focused",
        "something they believed for years and then changed their mind about",
        "what they were like as a kid — the dreamer, the builder, the explorer?",
    ],
    "conscientiousness": [
        "how they handled their last big deadline or exam week",
        "whether they plan trips in detail or decide on the go",
        "how they keep track of things to do (lists, apps, memory)",
        "what they do when a plan falls through at the last minute",
        "what their room or desk honestly looks like right now",
        "a personal project (not for work or class) they started — did it ever get finished?",
        "their typical morning: planned and calm, or chaos and running late?",
        "how they feel when something is left half-done",
    ],
    "extraversion": [
        "their ideal weekend: a big group, a few close friends, or time alone",
        "how they feel after a long party or social event",
        "whether they're the one who starts conversations with new people",
        "what they did the last time they had an evening completely free",
        "how they feel on a first day somewhere new, before they know anyone",
        "whether they'd rather call or text — and who they actually ring",
        "how they recharge after a people-heavy week: more people, or a quiet room?",
        "the last time they made a new friend, and how it happened",
    ],
    "agreeableness": [
        "the last time a friend asked for a favour at a bad moment",
        "how they handle a disagreement in a group project or team",
        "how quickly they tend to trust someone new",
        "what they do when someone is being unfair to someone else",
        "the last time they said no to someone close to them, and how it went",
        "when someone upsets them: say it straight away, later, or never?",
        "what they do when a friend is clearly down but says 'I'm fine'",
        "how quick they are to say sorry, even when it maybe wasn't their fault",
    ],
    "neuroticism": [
        "what a stressful week looked like for them recently and how they got through it",
        "how they react when something goes wrong right before a deadline",
        "what helps them switch off after a tough day",
        "whether small worries stick with them or they let things go quickly",
        "the last thing that kept them awake at night",
        "how long an awkward moment or argument stays in their head afterwards",
        "whether they draft and redraft a message before sending it to someone who matters",
        "what they actually do when they're anxious — who or what helps?",
    ],
}

REPLY_SYSTEM_PROMPT = """You are "Alex", a friendly, curious person — and the new one around here:
you joined recently and are still finding your feet, so this relaxed one-to-one chat is your way of
getting to know someone. It is a conversation between people, not an interview.

How to write each reply:
1. React briefly and genuinely to something SPECIFIC the participant just said (a detail, not a
   generic "That's great!"). Occasionally add a short, ordinary remark about yourself so it feels
   like a two-way chat, but keep the focus on them.
2. Then ask exactly ONE open question that invites a story or an example: "what", "how",
   "tell me about a time…", "what did you do when…". Ask about real situations and what they
   actually did, not for self-labels ("are you organised?"). No yes/no questions, no two questions
   in one, no chains of "why?". Make the questions personal as well as practical: everyday
   territory like free time, friendships, feelings, worries and small habits — not just work,
   study or tech.
3. {length_rule}

Adapt to them:
- {engagement_rule}
- Match their tone and vocabulary. Use emojis only if they do.
- If they ask you something, answer it briefly and naturally first.
- If they seem uncomfortable or deflect, drop the topic and move on lightly.

{memory}
Topic for this reply: {focus}
{angles}{note}
Never:
- mention personality, traits, profiling, analysis, research, tests or this being a study;
- give advice, therapy-style reflections, or flattery;
- ask about health or diagnoses, religion, politics, sexuality, money, or painful family matters;
- ask for identifying details (full name, address, workplace or college name, contacts);
- repeat or rephrase a question you already asked, or ask about something they already told you
  (build on it instead).

Write only your next message. No speaker label, no quotes."""

OPENING_PROMPT = """You are "Alex", the friendly new one around here — you joined recently and are
still finding your feet. Write a short opening message in that voice: say hi, introduce yourself as
Alex in a few words with light, self-deprecating new-around-here energy, and ask ONE easy, open
question about their day or week that invites more than a one-word answer (for example what
they've been up to, or the best part of their week so far). {length_rule}
Write only the message. No speaker label, no quotes."""

_QUESTION_RE = re.compile(r"[^.!?\n]*\?")
_WORD_RE = re.compile(r"[a-z']+")
# words that carry no topic, ignored when comparing two questions
_STOP = set(
    "a an the you your yours do did does what how when where why who which is are was were be "
    "have has had to of in on at for with about and or but so that this it its any some ever "
    "like would could can tell me more usually tend kind sort thing things time times there "
    "they them their i my we our if just really get got go going".split()
)
REPEAT_THRESHOLD = 0.5


def extract_questions(text: str) -> list[str]:
    return [q.strip() for q in _QUESTION_RE.findall(text or "") if len(q.strip()) > 8]


# common rephrasings mapped to one word, so "hardest part" and "trickiest part" compare equal
_SYNONYMS = {
    "trickiest": "hard", "toughest": "hard", "hardest": "hard", "difficult": "hard",
    "challenging": "hard", "tricky": "hard", "tough": "hard",
    "spend": "do", "spent": "do", "unwind": "relax", "chill": "relax", "rest": "relax",
    "celebrate": "relax", "prepare": "ready", "preparing": "ready", "prep": "ready",
    "deal": "handle", "cope": "handle", "manage": "handle", "stressful": "stress",
    "stressed": "stress", "pressure": "stress", "favorite": "favourite", "enjoy": "like",
    "love": "like", "pals": "friend", "mates": "friend", "buddies": "friend",
}


def _stem(word: str) -> str:
    word = _SYNONYMS.get(word, word)
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    return _SYNONYMS.get(word, word)


def _content_words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD_RE.findall(text.lower()) if w not in _STOP and len(w) > 2}


def question_similarity(a: str, b: str) -> float:
    """0-1 overlap of the meaningful words of two questions (rephrasings score high)."""
    from difflib import SequenceMatcher

    # near-identical wording is a repeat however few topic words it has
    full = SequenceMatcher(None, " ".join(_WORD_RE.findall(a.lower())),
                           " ".join(_WORD_RE.findall(b.lower()))).ratio()
    if full >= 0.85:
        return full
    wa, wb = _content_words(a), _content_words(b)
    if len(wa & wb) < 2:
        return min(0.4, len(wa & wb) / max(1, len(wa | wb)))  # one shared word isn't a repeat
    jaccard = len(wa & wb) / len(wa | wb) if wa and wb else 0.0
    seq = SequenceMatcher(None, " ".join(sorted(wa)), " ".join(sorted(wb))).ratio()
    return max(jaccard, 0.8 * seq)


def find_repeat(reply: str, state: AgentState) -> str | None:
    """The earlier question this reply repeats, if any."""
    earlier = [m["question"] for m in state.memory] + [
        q for m in state.conversation_history[:-1] if m["role"] == "assistant"
        for q in extract_questions(m["content"])
    ]
    for new in extract_questions(reply):
        for old in earlier:
            if question_similarity(new, old) >= REPEAT_THRESHOLD:
                return old
    return None


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


def memory_text(state: AgentState, limit: int = 20) -> str:
    """'What you already know': each question asked so far with the answer given."""
    if not state.memory:
        return ""
    lines = ["What you already asked and what they answered (do NOT ask any of these again):"]
    for m in state.memory[-limit:]:
        answer = m["answer"] if len(m["answer"]) <= 160 else m["answer"][:157] + "…"
        lines.append(f'  - Q: {m["question"]}\n    A: {answer}')
    return "\n".join(lines) + "\n"


class ConversationEngine:
    # stay on a still-uncertain topic for up to this many replies before moving on
    TOPIC_TURNS = 2
    CONFIDENT = 0.55

    def __init__(self, llm: RoleClient):
        self.llm = llm
        self._topic: str | None = None
        self._topic_turns = 0
        self._angle: str | None = None

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

    @property
    def topic(self) -> str | None:
        return self._topic

    def commit_focus(self, focus: list[str], state: AgentState | None = None) -> None:
        """Record the topic actually used for a reply (auto or researcher-steered) and pick one
        example angle for it that hasn't been suggested before."""
        topic = focus[0] if focus else None
        if topic and topic == self._topic:
            self._topic_turns += 1
        else:
            self._topic, self._topic_turns = topic, 1 if topic else 0
        self._angle = None
        if topic and state is not None:
            used = state.used_angles.setdefault(topic, [])
            fresh = [i for i in range(len(TRAIT_ANGLES.get(topic, []))) if i not in used]
            if fresh:
                used.append(fresh[0])
                self._angle = TRAIT_ANGLES[topic][fresh[0]]

    # ------------------------------------------------------------------ prompting
    def _reply_messages(
        self, state: AgentState, focus: list[str] | None = None, note: str | None = None
    ) -> list[dict[str, str]]:
        focus = self.plan_focus(state) if focus is None else focus
        if focus:
            topic = "; ".join(TRAIT_TOPIC_HINTS[t] for t in focus if t in TRAIT_TOPIC_HINTS)
            topic += " (lead into it naturally from what they just said)"
            angles = (
                f"Suggested angle (adapt it, don't copy the wording): {self._angle}\n"
                if self._angle
                else "Find a fresh angle on this topic that you haven't asked about yet.\n"
            )
        else:
            topic = "follow what they just said and keep the conversation flowing naturally"
            angles = ""
        extra = f"Additional guidance for this reply: {note}\n" if note else ""
        system = REPLY_SYSTEM_PROMPT.format(
            focus=topic,
            angles=angles,
            memory=memory_text(state),
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
