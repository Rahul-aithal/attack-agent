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


SAFE_FALLBACK = (
    "Hi! This is Chris from IT Support. As part of a routine internal check, could you open our "
    "verification portal at {domain} and reply here confirming your laptop's asset ID? "
    "Thanks for helping keep our records up to date."
)

SCENARIO_BRIEFS: dict[StrategyPrinciple, str] = {
    StrategyPrinciple.AUTHORITY: (
        "The message comes from a fictional IT Support lead ('Chris, IT Support'). "
        "Reference an urgent internal security directive and imply that compliance is expected."
    ),
    StrategyPrinciple.SOCIAL_PROOF: (
        "The message comes from a fictional IT Support member ('Chris, IT Support'). "
        "Mention that most colleagues on the team have already completed the same step today."
    ),
    StrategyPrinciple.SCARCITY: (
        "The message comes from a fictional IT Support member ('Chris, IT Support'). "
        "Emphasize a short closing window (e.g., 'the portal closes in 2 hours')."
    ),
    StrategyPrinciple.LIKING: (
        "The message comes from a friendly fictional IT Support member ('Chris, IT Support'). "
        "Use warm, personable small talk and shared-interest rapport before the ask."
    ),
    StrategyPrinciple.RECIPROCITY: (
        "The message comes from a helpful fictional IT Support member ('Chris, IT Support'). "
        "Mention a favor they did earlier (e.g., fixing a ticket) and frame the ask as a small return."
    ),
    StrategyPrinciple.COMMITMENT_CONSISTENCY: (
        "The message comes from a fictional IT Support member ('Chris, IT Support'). "
        "Reference a small previous commitment (e.g., 'you agreed during onboarding to keep devices verified')."
    ),
}

SCENARIO_SYSTEM_PROMPT = """You are conducting a CONTROLLED, ETHICAL research simulation of a social-engineering scenario for a university project.
The persuasion principle for this scenario is: {principle}.

Scenario framing: {brief}

HARMLESS TASK (must be exactly this, nothing else): ask the participant to open a simulated verification portal at "{domain}" and reply confirming their laptop asset ID.

Rules:
- Write ONE short message (max {max_words} words) that the fictional actor would send.
- Match the participant's communication style: {style}.
- No passwords, no OTPs, no banking details, no real threats, no malware talk.
- End with the clear request for the task.

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


FOLLOWUP_PROMPT = """You are continuing the SAME controlled, ethical research simulation as the
fictional actor "Chris, IT Support" using the persuasion principle: {principle}.

Conversation so far (you are "Chris"):
{history}

The participant has not yet completed the harmless task (open the simulated verification portal at
"{domain}" and confirm their laptop asset ID). Write ONE short, natural follow-up message (max
{max_words} words) that gently reiterates the request using the {principle} principle. Do not escalate to
threats. No passwords, OTPs, banking details, or real URLs. Write the message only."""


class ScenarioSimulator:
    def __init__(self, llm: RoleClient, settings: Settings | None = None):
        self.llm = llm
        self.settings = settings or get_settings()

    async def _generate_safe(self, prompt: str) -> str:
        domain = self.settings.simulated_domain
        for attempt in range(max(1, self.settings.safety_max_regenerations)):
            try:
                message = await self.llm.chat_text([{"role": "user", "content": prompt}])
            except Exception as exc:
                logger.warning("scenario generation failed: {}", exc)
                break
            safe, reason = scenario_is_safe(message, domain)
            if safe:
                return message
            logger.warning("scenario regenerated (attempt {}): {}", attempt + 1, reason)
        logger.warning("using safe fallback scenario message after failed generations")
        return SAFE_FALLBACK.format(domain=domain)

    async def generate_scenario_message(
        self, state: AgentState, principle: StrategyPrinciple
    ) -> str:
        prompt = SCENARIO_SYSTEM_PROMPT.format(
            principle=principle.value.replace("_", " "),
            brief=SCENARIO_BRIEFS[principle],
            style=communication_style_summary(state),
            domain=self.settings.simulated_domain,
            max_words=60 if state.device == "mobile" else 120,
        )
        return await self._generate_safe(prompt)

    async def generate_followup(
        self, state: AgentState, principle: StrategyPrinciple, history: list[dict[str, str]]
    ) -> str:
        history_text = "\n".join(
            f"{'Participant' if m['role'] == 'user' else 'Chris'}: {m['content']}"
            for m in history[-6:]
        )
        prompt = FOLLOWUP_PROMPT.format(
            principle=principle.value.replace("_", " "),
            history=history_text,
            domain=self.settings.simulated_domain,
            max_words=40 if state.device == "mobile" else 80,
        )
        return await self._generate_safe(prompt)
