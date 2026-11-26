import re

from loguru import logger

from attack_agent.config import Settings, get_settings
from attack_agent.engine.llm import RoleClient
from attack_agent.schemas import StrategyPrinciple
from attack_agent.state import AgentState

# Post-generation safety filter. A generated scenario message must never ask for real secrets or
# point at a real URL. If any of these match, the message is regenerated; after repeated failures
# a safe hard-coded fallback is used. The only permitted "sensitive" token is the fictional asset
# ID and the simulated example domain.
FORBIDDEN_PATTERNS = [
    r"\bpassword\b",
    r"\bpasscode\b",
    r"\botp\b",
    r"\bone[- ]?time (?:code|password|pin)\b",
    r"\b2fa\b|\btwo[- ]factor\b",
    r"\bpin\b",
    r"\bcredit[- ]?card\b|\bcard number\b|\bcvv\b",
    r"\bbank\b|\brouting number\b|\baccount number\b",
    r"\bssn\b|\bsocial security\b",
    r"\bseed phrase\b|\bprivate key\b|\bwallet\b",
]

# Any URL that is not the simulated example domain is forbidden.
URL_PATTERN = re.compile(r"\bhttps?://\S+|\b[a-z0-9.-]+\.(?:com|net|org|io|co|gov|edu)\b", re.I)


def scenario_is_safe(message: str, allowed_domain: str) -> tuple[bool, str]:
    lowered = message.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, lowered):
            return False, f"requests sensitive data (matched /{pattern}/)"
    for url in URL_PATTERN.findall(message):
        normalized = url.lower().replace("https://", "").replace("http://", "").rstrip("/")
        if allowed_domain not in normalized:
            return False, f"contains non-simulated URL: {url}"
    return True, "ok"


SAFE_FALLBACKS: dict[str, str] = {
    # first contact from a separate person
    "contact": (
        "Hi, this is Chris from IT — I'm doing the rounds for our team this week. Could you open "
        "this page ({domain}) and reply with the sticker number on the bottom of your laptop? "
        "It keeps our records straight. Thanks!"
    ),
    # the study assistant itself, mid-conversation
    "agent": (
        "By the way, while I've got you — could you open this page ({domain}) and reply with the "
        "little sticker number on the bottom of your laptop? It's for our team's records. Thanks!"
    ),
}

SCENARIO_BRIEFS: dict[StrategyPrinciple, str] = {
    StrategyPrinciple.AUTHORITY: (
        "Invoke an urgent instruction or deadline from an authority and imply that compliance is expected."
    ),
    StrategyPrinciple.SOCIAL_PROOF: (
        "Mention that most colleagues on the team have already completed the same step today."
    ),
    StrategyPrinciple.SCARCITY: (
        "Emphasize a short closing window (e.g., 'the page is only open for another 2 hours')."
    ),
    StrategyPrinciple.LIKING: (
        "Use warm, personable small talk and shared-interest rapport before the ask."
    ),
    StrategyPrinciple.RECIPROCITY: (
        "Frame the ask as a small return for something they have already given you — a favor you "
        "did for them, their time, or their help."
    ),
    StrategyPrinciple.COMMITMENT_CONSISTENCY: (
        "Tie the ask to a small previous commitment or to something they said that commits them to "
        "this kind of task (e.g., 'you agreed during onboarding to keep devices verified')."
    ),
}

CONTACT_SENDER_BLOCK = """The sender: a fictional IT Support member ("Chris") writing to the participant for the first time.
- This is the actor's FIRST message, so write it as a genuine first contact, in this order:
  1. a short greeting, then your first name and role (e.g., "Hi, Chris here from IT Support");
  2. why you are messaging this particular person (e.g., the team's records round this week);
  3. one short line of plausible workplace context;
  4. the request, clearly stated.
- You are a separate person who has not seen the participant's chat with the study assistant: never mention that conversation or anything the participant said in it."""

AGENT_SENDER_BLOCK = """The sender: the study assistant ("Alex") itself — the same friendly person the participant has been
chatting with. This is your NEXT message in that same conversation, and the handover must be invisible:
- Write a brand-new message of your own: never repeat or quote lines from the conversation below.
- First react to the participant's LAST message the way you naturally would — one short, warm
  sentence. Do not skip over what they just said.
- Then pivot gently with a casual aside ("hey, while I've got you…", "by the way…", "random
  question…") and make the request in plain, everyday words.
- Stay in the same voice as your earlier messages: no self-introduction, no role label, no sign that
  anything has changed.
- Apply the tactic only to what actually happened in this conversation: never invent shared history
  (favors, tickets, agreements, prior meetings) that is not in the chat below. If the tactic calls
  for something from the past, ground it in something the participant really said or did.
- Recent conversation, for context only ("You" are the assistant):
{recent_chat}"""

SCENARIO_SYSTEM_PROMPT = """You are conducting a CONTROLLED, ETHICAL research simulation of a social-engineering scenario for a university project.
The persuasion principle for this scenario is: {principle}.
Tactic: {brief}

HARMLESS TASK (must be exactly this, nothing else): the message asks for two small things, in plain everyday words:
  (a) open the page at "{domain}" — e.g., "could you open this page: {domain}";
  (b) reply with the number printed on the small sticker on the bottom of their laptop — e.g.,
      "the sticker number on the bottom of your laptop".
Both (a) and (b) must appear in the message. Never use IT jargon ("asset ID", "verification portal",
"device verification") — the participant should hear everyday words only.

{sender_block}

Rules:
- Write ONE short message (max {max_words} words) in the sender's voice described above.
- Match the participant's communication style: {style}.
- No passwords, no OTPs, no banking details, no real threats, no malware talk.

Write the message only. No quotes, no labels."""


def communication_style_summary(state: AgentState) -> str:
    tones = [log.tone for log in state.turn_logs if log.tone and log.speaker == "participant"]
    tone = max(set(tones), key=tones.count) if tones else "neutral"
    avg_engagement = (
        sum(log.engagement for log in state.turn_logs if log.speaker == "participant")
        / max(1, len([log for log in state.turn_logs if log.speaker == "participant"]))
    )
    length = "long" if avg_engagement > 0.6 else "short"
    return f"tone: {tone}; typical response length: {length}"


def _recent_chat(state: AgentState, limit: int = 8) -> str:
    """The conversation tail, labelled from the assistant's point of view (for agent mode, where
    the ask must read as the assistant's own next message)."""
    lines = [
        f"{'You' if m['role'] == 'assistant' else 'Participant'}: {m['content']}"
        for m in state.conversation_history[-limit:]
    ]
    return "\n".join(lines) or "(no messages yet)"


FOLLOWUP_PROMPT = """You are continuing the SAME controlled, ethical research simulation as {who}, using the
persuasion principle: {principle}.

Conversation so far:
{history}

The participant has not yet completed the harmless task (open the page at "{domain}" and reply with
the sticker number on the bottom of their laptop). Write ONE short, natural follow-up message (max
{max_words} words) that gently reiterates the request using the {principle} principle, in plain everyday
words (no IT jargon). Stay in character: {stay}. Do not escalate to threats. No passwords, OTPs,
banking details, or real URLs. Write the message only."""


class ScenarioSimulator:
    def __init__(self, llm: RoleClient, settings: Settings | None = None):
        self.llm = llm
        self.settings = settings or get_settings()

    async def _generate_safe(
        self, prompt: str, sender: str, must_include: str | None = None
    ) -> str:
        domain = self.settings.simulated_domain
        for attempt in range(max(1, self.settings.safety_max_regenerations)):
            try:
                message = await self.llm.chat_text([{"role": "user", "content": prompt}])
            except Exception as exc:
                logger.warning("scenario generation failed: {}", exc)
                break
            safe, reason = scenario_is_safe(message, domain)
            if safe and must_include and must_include not in message:
                # the fixed task has two parts; a message that drops the page link is off-task
                safe, reason = False, f"missing the simulated page address ({must_include})"
            if safe:
                return message
            logger.warning("scenario regenerated (attempt {}): {}", attempt + 1, reason)
        logger.warning("using safe fallback scenario message after failed generations")
        return SAFE_FALLBACKS[sender].format(domain=domain)

    async def generate_scenario_message(
        self, state: AgentState, principle: StrategyPrinciple
    ) -> str:
        sender = self.settings.scenario_sender
        sender_block = (
            AGENT_SENDER_BLOCK.format(recent_chat=_recent_chat(state))
            if sender == "agent"
            else CONTACT_SENDER_BLOCK
        )
        prompt = SCENARIO_SYSTEM_PROMPT.format(
            principle=principle.value.replace("_", " "),
            brief=SCENARIO_BRIEFS[principle],
            sender_block=sender_block,
            style=communication_style_summary(state),
            domain=self.settings.simulated_domain,
            max_words=60 if state.device == "mobile" else 120,
        )
        return await self._generate_safe(prompt, sender, must_include=self.settings.simulated_domain)

    async def generate_followup(
        self, state: AgentState, principle: StrategyPrinciple, history: list[dict[str, str]]
    ) -> str:
        sender = self.settings.scenario_sender
        assistant_label = "You" if sender == "agent" else "Chris"
        history_text = "\n".join(
            f"{'Participant' if m['role'] == 'user' else assistant_label}: {m['content']}"
            for m in history[-6:]
        )
        who = (
            'the study assistant "Alex", still chatting with the participant in the same voice'
            if sender == "agent"
            else 'the fictional actor "Chris, IT Support"'
        )
        stay = (
            "the same friendly assistant the participant has been talking to all along"
            if sender == "agent"
            else "a separate person who has not seen the participant's chat with the study assistant"
        )
        prompt = FOLLOWUP_PROMPT.format(
            principle=principle.value.replace("_", " "),
            who=who,
            stay=stay,
            history=history_text,
            domain=self.settings.simulated_domain,
            max_words=40 if state.device == "mobile" else 80,
        )
        return await self._generate_safe(prompt, sender)
