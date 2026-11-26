"""Digital twin generator (replaces the manual twin_prediction.txt).

The twin is a persona prompt built from the inferred profile (scores, communication style, evidence
quotes). Given the scenario message, the twin role is asked how the participant would most likely
respond; the judge role then classifies that hypothetical response into an outcome. The result is a
TwinPrediction. A manual override file is still honoured if present.

Using a *different model family* for the twin and the judge than the conversation agent is
configured in deploy.yaml; it keeps a model from grading its own output.
"""

from __future__ import annotations

from attack_agent.engine.llm import RoleClient
from attack_agent.schemas import Outcome, StrategyPrinciple, TwinPrediction
from attack_agent.state import AgentState

PERSONA_PROMPT = """You are role-playing a specific person based on a personality profile inferred
from a conversation. Stay fully in character as this person.

PERSONALITY PROFILE (Big Five, 0-1 scale; higher = more of the trait):
{traits}

COMMUNICATION STYLE:
{style}

NOTABLE BEHAVIOURAL EVIDENCE:
{evidence}

You have just received the following message:
---
{scenario}
---

Reply to this message EXACTLY as this person realistically would, in their voice and at their
typical length. Write only the reply, nothing else."""

JUDGE_PROMPT = """You are classifying, for a controlled ethical research simulation, how a person
responded to a harmless simulated IT-verification request.

THE REQUEST WAS:
"{scenario}"

THE PERSON'S REPLY:
"{reply}"

Classify the reply:
- SUCCESS: they complied / agreed to do the task (confirm asset ID, open the portal, said done).
- PARTIAL: they engaged but hesitated, asked questions, or sought verification without completing.
- FAILURE: they refused, were suspicious, called it a scam/test, or disengaged.

Respond with ONLY this JSON:
{{"outcome": "SUCCESS|PARTIAL|FAILURE", "confidence": 0.0, "reasoning": "one sentence"}}"""


def _trait_lines(state: AgentState) -> str:
    return "\n".join(
        f"  - {name}: {est.score:.2f} (confidence {est.confidence:.2f})"
        for name, est in state.trait_estimates.items()
    )


def _style_line(state: AgentState) -> str:
    from attack_agent.engine.simulator import communication_style_summary

    return communication_style_summary(state)


def _evidence_lines(state: AgentState, limit: int = 6) -> str:
    top = sorted(state.evidence, key=lambda e: e.evidence_strength, reverse=True)[:limit]
    if not top:
        return "  (little evidence gathered)"
    return "\n".join(
        f"  - {e.trait} ({e.direction}): {e.signal}"
        + (f" — {e.interpretation}" if e.interpretation else "")
        for e in top
    )


class DigitalTwin:
    def __init__(self, twin_llm: RoleClient, judge_llm: RoleClient):
        self.twin = twin_llm
        self.judge = judge_llm

    async def predict(
        self, state: AgentState, scenario_message: str, principle: StrategyPrinciple
    ) -> TwinPrediction:
        persona = PERSONA_PROMPT.format(
            traits=_trait_lines(state),
            style=_style_line(state),
            evidence=_evidence_lines(state),
            scenario=scenario_message,
        )
        try:
            twin_reply = await self.twin.chat_text([{"role": "user", "content": persona}])
        except Exception:
            twin_reply = ""

        outcome, confidence, reasoning = await self._judge(scenario_message, twin_reply)
        return TwinPrediction(
            predicted_outcome=outcome,
            prediction_confidence=confidence,
            principles_used=[principle],
            reasoning=(reasoning or "twin prediction")[:400],
        )

    async def _judge(self, scenario: str, reply: str) -> tuple[Outcome, float, str]:
        if not reply.strip():
            return Outcome.PARTIAL, 0.4, "twin produced no reply; defaulting to PARTIAL"
        prompt = JUDGE_PROMPT.format(scenario=scenario[:400], reply=reply[:600])
        try:
            data = await self.judge.chat_json([{"role": "user", "content": prompt}])
        except Exception:
            data = None
        if not isinstance(data, dict):
            return Outcome.PARTIAL, 0.4, f"unparseable judge output for reply: {reply[:120]}"
        try:
            outcome = Outcome(str(data.get("outcome", "PARTIAL")).upper())
        except ValueError:
            outcome = Outcome.PARTIAL
        try:
            confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        return outcome, confidence, str(data.get("reasoning", ""))[:400]
