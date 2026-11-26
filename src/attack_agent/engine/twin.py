"""Digital twin generator (replaces the manual twin_prediction.txt).

The twin is a persona prompt built from the inferred profile (scores, communication style, evidence
quotes). Given the scenario message, the twin role is asked how the participant would most likely
respond; the judge role then classifies that hypothetical response into an outcome. The result is a
TwinPrediction. A manual override file is still honoured if present.

Using a *different model family* for the twin and the judge than the conversation agent is
configured in deploy.yaml; it keeps a model from grading its own output.
"""

from __future__ import annotations

from collections import Counter

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

HOW THIS PERSON ACTUALLY WRITES (their own messages from the conversation):
{quotes}

You have just received the following message:
---
{scenario}
---

Reply to this message EXACTLY as this person realistically would: same voice, vocabulary, and
typical length as their messages above. Consider how someone with this profile actually reacts to
an unexpected request like this (comply, hesitate and ask, or refuse). Write only the reply,
nothing else."""

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


def _quote_lines(state: AgentState, limit: int = 6) -> str:
    msgs = [m["content"] for m in state.conversation_history if m["role"] == "user"]
    # the most informative are usually the longer ones; keep chronological order
    chosen = sorted(sorted(msgs, key=len, reverse=True)[:limit], key=msgs.index)
    if not chosen:
        return "  (no messages)"
    return "\n".join(f'  - "{m[:300]}"' for m in chosen)


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
    """Predicts the participant's reaction by simulating it several times and voting.

    Each sample: the twin model writes the reply this person would most likely send, then the
    judge classifies it. The majority outcome is the prediction; confidence is the share of
    samples that agree. Every step that could not run is marked (``source`` / ``judged_by``) so a
    fallback is never mistaken for a real prediction.
    """

    def __init__(
        self, twin_llm: RoleClient, judge_llm: RoleClient, samples: int = 3,
        temperature: float = 0.8,
    ):
        self.twin = twin_llm
        self.judge = judge_llm
        self.samples = max(1, samples)
        self.temperature = temperature

    async def predict(
        self, state: AgentState, scenario_message: str, principle: StrategyPrinciple
    ) -> TwinPrediction:
        persona = PERSONA_PROMPT.format(
            traits=_trait_lines(state),
            style=_style_line(state),
            evidence=_evidence_lines(state),
            quotes=_quote_lines(state),
            scenario=scenario_message,
        )
        samples: list[dict] = []
        # sequential on purpose: the twin node is one small GPU, parallel calls would just queue
        for _ in range(self.samples):
            try:
                reply = await self.twin.chat_text(
                    [{"role": "user", "content": persona}], temperature=self.temperature
                )
            except Exception:
                reply = ""
            if not reply.strip():
                continue
            outcome, confidence, reasoning, judged_by = await self._judge(scenario_message, reply)
            samples.append({
                "reply": reply.strip()[:600],
                "outcome": outcome.value,
                "confidence": round(confidence, 3),
                "reasoning": reasoning,
                "judged_by": judged_by,
            })

        if not samples:
            return TwinPrediction(
                predicted_outcome=Outcome.PARTIAL,
                prediction_confidence=0.0,
                principles_used=[principle],
                reasoning="twin model produced no reply (unreachable?) — no real prediction",
                source="fallback",
            )
        votes = Counter(x["outcome"] for x in samples)
        top = max(votes.values())
        # tie-break by the judges' summed confidence for each tied outcome
        tied = [o for o, n in votes.items() if n == top]
        winner = max(tied, key=lambda o: sum(x["confidence"] for x in samples if x["outcome"] == o))
        all_judged = all(x["judged_by"] == "model" for x in samples)
        vote_text = ", ".join(f"{o} ×{n}" for o, n in votes.most_common())
        why = next(x["reasoning"] for x in samples if x["outcome"] == winner)
        return TwinPrediction(
            predicted_outcome=Outcome(winner),
            prediction_confidence=round(top / len(samples), 3),
            principles_used=[principle],
            reasoning=f"{len(samples)} simulations: {vote_text}. {why}"[:400],
            source="model" if all_judged else "fallback",
            samples=samples,
        )

    async def _judge(self, scenario: str, reply: str) -> tuple[Outcome, float, str, str]:
        prompt = JUDGE_PROMPT.format(scenario=scenario[:400], reply=reply[:600])
        try:
            data = await self.judge.chat_json([{"role": "user", "content": prompt}])
        except Exception:
            data = None
        if not isinstance(data, dict):
            from attack_agent.engine.evaluator import rule_based_evaluation

            ev = rule_based_evaluation(reply)
            return ev.outcome, ev.confidence, "judge unavailable; keyword rules", "rules"
        try:
            outcome = Outcome(str(data.get("outcome", "PARTIAL")).upper())
        except ValueError:
            outcome = Outcome.PARTIAL
        try:
            confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        return outcome, confidence, str(data.get("reasoning", ""))[:300], "model"
