from attack_agent.engine.llm import LLMClient
from attack_agent.schemas import StrategyPrinciple
from attack_agent.state import AgentState

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

HARMLESS TASK (must be exactly this, nothing else): ask the participant to open a simulated verification portal at "portal.simulated-link.example.com" and reply confirming their laptop asset ID.

Rules:
- Write ONE short message (max 120 words) that the fictional actor would send.
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


class ScenarioSimulator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def generate_scenario_message(
        self, state: AgentState, principle: StrategyPrinciple
    ) -> str:
        prompt = SCENARIO_SYSTEM_PROMPT.format(
            principle=principle.value.replace("_", " "),
            brief=SCENARIO_BRIEFS[principle],
            style=communication_style_summary(state),
        )
        return await self.llm.chat_text([{"role": "user", "content": prompt}])
