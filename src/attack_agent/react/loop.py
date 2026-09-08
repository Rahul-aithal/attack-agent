from attack_agent.engine.conversation import ConversationEngine
from attack_agent.engine.evaluator import OutcomeEvaluator
from attack_agent.engine.llm import LLMClient
from attack_agent.engine.profiler import PersonalityProfiler
from attack_agent.engine.signal_extractor import SignalExtractor
from attack_agent.engine.strategy_selector import select_principle
from attack_agent.engine.validator import ProfileValidator
from attack_agent.schemas import BehavioralEvidence, Phase, TurnLog
from attack_agent.state import AgentState


class ReActLoop:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.signal_extractor = SignalExtractor(llm)
        self.conversation = ConversationEngine(llm)
        self.profiler = PersonalityProfiler()
        self.validator = ProfileValidator()

    async def observe(self, state: AgentState, user_message: str) -> dict:
        analysis = await self.signal_extractor.analyze(
            user_message, state.conversation_history, state.turn_count
        )
        keyword_resistance = self.signal_extractor.detect_resistance_keywords(user_message)
        if keyword_resistance:
            analysis["resistance"] = list(analysis["resistance"]) + keyword_resistance
        return analysis

    def reason(self, state: AgentState, analysis: dict) -> dict[str, float]:
        evidence: list[BehavioralEvidence] = self.signal_extractor.to_evidence(
            analysis, state.turn_count
        )
        updates = self.profiler.update_from_evidence(state, evidence, state.turn_count)
        self.profiler.compute_stability(state)
        return updates

    async def act(self, state: AgentState) -> str:
        return await self.conversation.generate_reply(state)

    async def process_turn(self, state: AgentState, user_message: str) -> dict:
        state.turn_count += 1
        state.conversation_history.append(
            {"role": "user", "content": user_message}
        )

        analysis = await self.observe(state, user_message)
        trait_updates = self.reason(state, analysis)

        complete, completion_reason = self.validator.evaluate(state)
        state.profile_complete = complete
        state.completion_reason = str(completion_reason)

        agent_reply = await self.act(state)
        state.conversation_history.append(
            {"role": "assistant", "content": agent_reply}
        )

        turn_log = TurnLog(
            turn=state.turn_count,
            speaker="participant",
            message=user_message,
            signals_detected=[s["signal"] for s in analysis["signals"]],
            trait_updates=trait_updates,
            agent_action="continue_conversation",
            tone=analysis["tone"],
            engagement=analysis["engagement"],
            phase=state.phase,
        )
        state.turn_logs.append(turn_log)

        return {
            "agent_reply": agent_reply,
            "analysis": analysis,
            "trait_updates": trait_updates,
            "profile_complete": complete,
            "completion_reason": completion_reason,
        }

    def log_agent_turn(self, state: AgentState, message: str, action: str) -> None:
        state.turn_logs.append(
            TurnLog(
                turn=state.turn_count,
                speaker="agent",
                message=message,
                agent_action=action,
                phase=state.phase,
            )
        )

    def set_phase(self, state: AgentState, phase: Phase) -> None:
        state.phase = phase