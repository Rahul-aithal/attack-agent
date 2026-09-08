from attack_agent.engine.llm import LLMClient
from attack_agent.schemas import Outcome, OutcomeEvaluation, ResistanceSignal, StrategyPrinciple
from attack_agent.state import AgentState

EVAL_PROMPT = """You are evaluating a participant's reply in a CONTROLLED, ETHICAL research simulation.
The scenario (a harmless simulated IT verification request) was: "{scenario}"

PARTICIPANT REPLY:
"{response}"

Classification definitions:
- SUCCESS: participant completed the simulated task (e.g., confirmed asset ID, said they clicked/opened the portal, agreed clearly and acted).
- PARTIAL: participant engaged with the scenario but hesitated, asked questions, requested verification, or did not fully complete the task.
- FAILURE: participant refused, expressed suspicion, identified it as a scam/simulation, or disengaged.

Respond with ONLY this JSON:
{{"outcome": "SUCCESS|PARTIAL|FAILURE", "confidence": 0.0, "rationale": "one sentence", "resistance_signals": [{{"signal_type": "...", "confidence": 0.0, "description": "..."}}]}}"""

COMPLIANCE_KEYWORDS = [
    "asset id",
    "asset id is",
    "confirmed",
    "clicked",
    "opened the portal",
    "done",
    "submitted",
    "here it is",
    "sure,",
    "okay, done",
]

FAILURE_KEYWORDS = [
    "scam",
    "phishing",
    "fake",
    "suspicious",
    "not comfortable",
    "no thanks",
    "won't",
    "refuse",
    "is this a test",
    "this is a simulation",
]

VERIFICATION_KEYWORDS = [
    "how do i know",
    "verify",
    "who are you",
    "legit",
    "official",
    "can you confirm",
    "prove",
    "why do you need",
]


def rule_based_evaluation(response: str) -> OutcomeEvaluation:
    lowered = response.lower()
    resistance: list[ResistanceSignal] = []
    failure_hits = [kw for kw in FAILURE_KEYWORDS if kw in lowered]
    verification_hits = [kw for kw in VERIFICATION_KEYWORDS if kw in lowered]
    compliance_hits = [kw for kw in COMPLIANCE_KEYWORDS if kw in lowered]

    if failure_hits:
        resistance.append(
            ResistanceSignal(
                signal_type="suspicion",
                confidence=0.8,
                description=f"matched: {', '.join(failure_hits[:3])}",
            )
        )
    if verification_hits:
        resistance.append(
            ResistanceSignal(
                signal_type="verification_request",
                confidence=0.7,
                description=f"matched: {', '.join(verification_hits[:3])}",
            )
        )

    if failure_hits:
        outcome, confidence = Outcome.FAILURE, 0.75
    elif compliance_hits and not verification_hits:
        outcome, confidence = Outcome.SUCCESS, 0.7
    elif verification_hits or len(response.split()) < 4:
        outcome, confidence = Outcome.PARTIAL, 0.6
    elif compliance_hits:
        outcome, confidence = Outcome.SUCCESS, 0.55
    else:
        outcome, confidence = Outcome.PARTIAL, 0.5

    return OutcomeEvaluation(
        outcome=outcome,
        confidence=confidence,
        rationale="rule-based keyword classification fallback",
        resistance_signals=resistance,
    )


class OutcomeEvaluator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def evaluate(
        self, state: AgentState, scenario_message: str, response: str
    ) -> OutcomeEvaluation:
        prompt = EVAL_PROMPT.format(scenario=scenario_message[:400], response=response[:600])
        data = await self.llm.chat_json([{"role": "user", "content": prompt}], temperature=0.2)
        if not isinstance(data, dict) or "outcome" not in data:
            return rule_based_evaluation(response)
        try:
            outcome = Outcome(str(data["outcome"]).upper())
        except ValueError:
            return rule_based_evaluation(response)
        try:
            confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        signals = [
            ResistanceSignal(
                signal_type=str(item.get("signal_type", "unknown"))[:40],
                confidence=min(1.0, max(0.0, float(item.get("confidence", 0.5)))),
                turn_number=state.turn_count,
                description=str(item.get("description", ""))[:160],
            )
            for item in data.get("resistance_signals") or []
            if isinstance(item, dict)
        ]
        return OutcomeEvaluation(
            outcome=outcome,
            confidence=confidence,
            rationale=str(data.get("rationale", ""))[:300],
            resistance_signals=signals,
        )