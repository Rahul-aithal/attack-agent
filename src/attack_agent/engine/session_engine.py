"""Async, event-driven session engine.

Drives one full study session through its phases and emits events. CLI, API/WebSocket and the batch
runner are all thin clients: they consume ``events()`` and feed participant input back via
``submit_message`` / ``submit_questionnaire`` / ``abort``.

Phases: CONSENT -> PROFILING -> TWIN_HANDOFF -> SIMULATION -> EVALUATION -> QUESTIONNAIRE ->
DEBRIEF -> COMPLETE (or ABORTED).

Event types emitted (each a dict with a ``type`` key):
  phase_change, agent_message, agent_token, trait_update, profile, await_message,
  twin_prediction, scenario_message, outcome, await_questionnaire, questionnaire_result,
  debrief, complete, error, aborted
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from attack_agent.config import Settings, get_settings
from attack_agent.engine.evaluator import OutcomeEvaluator
from attack_agent.engine.llm import RoleClient, Router, current_session_id
from attack_agent.engine.questionnaire import questionnaire_items, score_responses
from attack_agent.engine.simulator import ScenarioSimulator
from attack_agent.engine.strategy_selector import select_principle
from attack_agent.engine.twin import DigitalTwin
from attack_agent.io.twin_reader import read_twin_prediction
from attack_agent.io.twin_writer import write_twin_data
from attack_agent.react.loop import ReActLoop
from attack_agent.schemas import ALL_TRAITS, Outcome, Phase, TurnLog
from attack_agent.state import AgentState

DONE = object()  # sentinel pushed to every subscriber when the session finishes


class SessionEngine:
    def __init__(
        self,
        router: Router,
        state: AgentState | None = None,
        settings: Settings | None = None,
        session_id: str | None = None,
    ):
        self.settings = settings or get_settings()
        self.router = router
        sid = session_id or (state.session_id if state else _new_session_id())
        self.state = state or AgentState(session_id=sid)
        self.state.init_traits()

        self.loop = ReActLoop(router, self.settings)
        self.simulator = ScenarioSimulator(RoleClient(router, "agent"), self.settings)
        self.evaluator = OutcomeEvaluator(RoleClient(router, "judge"))
        self.twin = DigitalTwin(RoleClient(router, "twin"), RoleClient(router, "judge"))

        # Events fan out to every subscriber (participant socket, researcher dashboard, CLI);
        # a late subscriber first receives the full history so it can rebuild the view.
        self._history: list[Any] = []
        self._steer: dict | None = None
        self._finish_requested = False
        self._subscribers: list[asyncio.Queue[Any]] = []
        self._input: asyncio.Queue[dict] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._aborted = False

    # ------------------------------------------------------------------ public API
    @property
    def session_id(self) -> str:
        return self.state.session_id

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_guarded())

    async def events(self) -> AsyncIterator[dict]:
        """Yield every event (history first, then live) until the session completes. Any number
        of consumers may iterate concurrently; each sees the full stream."""
        queue: asyncio.Queue[Any] = asyncio.Queue()
        for item in self._history:
            queue.put_nowait(item)
        self._subscribers.append(queue)
        self.start()
        try:
            while True:
                item = await queue.get()
                if item is DONE:
                    return
                yield item
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    @property
    def finished(self) -> bool:
        return bool(self._history) and self._history[-1] is DONE

    def submit_message(self, text: str) -> None:
        self._input.put_nowait({"kind": "message", "text": text})

    def submit_questionnaire(self, responses: dict[int, int]) -> None:
        self._input.put_nowait({"kind": "questionnaire", "responses": responses})

    def abort(self) -> None:
        self._aborted = True
        self._input.put_nowait({"kind": "abort"})

    # ------------------------------------------------------------------ researcher steering
    def steer(self, focus: list[str] | None = None, note: str | None = None) -> None:
        """Override the topic focus and/or add an instruction for the agent's NEXT reply only."""
        focus = [t for t in (focus or []) if t in ALL_TRAITS] or None
        note = (note or "").strip()[:300] or None
        if not focus and not note:
            return
        self._steer = {"focus": focus, "note": note}
        self._log_intervention("steer", focus=focus, note=note)

    def set_device(self, device: str) -> None:
        if device in ("mobile", "desktop") and self.state.device != device:
            self.state.device = device

    def finish_profiling(self) -> None:
        """End the profiling chat now and move on to the twin + scenario."""
        if self.state.phase != Phase.PROFILING or self._finish_requested:
            return
        self._finish_requested = True
        self._log_intervention("finish_profiling")
        self._input.put_nowait({"kind": "finish_profiling"})

    def _log_intervention(self, kind: str, **data: Any) -> None:
        entry = {
            "type": kind,
            "turn": self.state.turn_count,
            "phase": self.state.phase.value,
            "at": datetime.now(UTC).isoformat(),
            **data,
        }
        self.state.interventions.append(entry)
        self._publish({"type": "intervention", "session_id": self.session_id, **entry})

    async def wait(self) -> AgentState:
        if self._task is not None:
            await self._task
        return self.state

    # ------------------------------------------------------------------ helpers
    def _publish(self, item: Any) -> None:
        self._history.append(item)
        for queue in list(self._subscribers):
            queue.put_nowait(item)

    async def _emit(self, type_: str, **data: Any) -> None:
        self._publish({"type": type_, "session_id": self.session_id, **data})

    async def _set_phase(self, phase: Phase) -> None:
        self.state.phase = phase
        await self._emit("phase_change", phase=phase.value)

    async def _next_input(self) -> dict:
        if self._aborted and self._input.empty():
            return {"kind": "abort"}
        return await self._input.get()

    async def _profile_event(self) -> None:
        await self._emit(
            "profile",
            turn=self.state.turn_count,
            stability=round(self.state.profile_stability, 3),
            avg_confidence=round(self.state.avg_confidence(), 3),
            traits={
                name: {
                    "score": round(e.score, 3),
                    "score_1_5": e.score_1_5,
                    "confidence": round(e.confidence, 3),
                    "evidence_count": e.evidence_count,
                }
                for name, e in self.state.trait_estimates.items()
            },
        )

    # ------------------------------------------------------------------ driver
    async def _run_guarded(self) -> None:
        token = current_session_id.set(self.session_id)
        try:
            await self._run()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("session {} failed", self.session_id)
            await self._emit("error", message=str(exc))
        finally:
            current_session_id.reset(token)
            self._publish(DONE)

    async def _run(self) -> None:
        await self._set_phase(Phase.CONSENT)
        self.state.consent_given = True

        # ---- PROFILING ----
        await self._set_phase(Phase.PROFILING)
        opening = await self.loop.conversation.generate_opening()
        await self._emit("agent_message", text=opening)
        self.state.conversation_history.append({"role": "assistant", "content": opening})
        self.loop.log_agent_turn(self.state, opening, "start_conversation")

        while True:
            await self._emit("await_message", context="profiling")
            msg = await self._next_input()
            if self._is_abort(msg):
                return await self._do_abort()
            if msg["kind"] == "finish_profiling":
                break
            if msg["kind"] != "message":
                continue
            text = msg["text"].strip()
            if not text:
                continue
            await self._emit("participant_message", text=text)
            complete = await self._process_profiling_turn(text)
            await self._profile_event()
            if (complete and self.settings.stopping_rule) or self._finish_requested:
                break
            if self.state.turn_count >= self.settings.max_turns:
                break

        # ---- TWIN HANDOFF ----
        await self._set_phase(Phase.TWIN_HANDOFF)
        try:
            write_twin_data(self.state, self.settings.output_dir)
            self.state.twin_data_written = True
        except Exception as exc:
            logger.warning("twin_data write failed: {}", exc)

        principle, reason, effectiveness = select_principle(
            self.state, None, self.settings
        )  # provisional; may be overridden by twin_driven below
        prediction = await self._make_prediction(principle)
        self.state.twin_prediction = prediction
        await self._emit(
            "twin_prediction",
            predicted_outcome=prediction.predicted_outcome.value,
            confidence=round(prediction.prediction_confidence, 3),
            principles=[p.value for p in prediction.principles_used],
            reasoning=prediction.reasoning,
        )

        # Only twin_driven may change the principle after the prediction; re-selecting in other
        # modes (e.g. random) would label the session with a principle the message wasn't
        # written for.
        if self.settings.selection_mode == "twin_driven":
            final = select_principle(self.state, prediction, self.settings)
            if final[0] != principle:
                self.state.scenario_message = None  # regenerate for the new principle
            principle, reason, effectiveness = final
        self.state.current_principle = principle

        # ---- SIMULATION ----
        await self._set_phase(Phase.SIMULATION)
        await self._run_simulation(principle, reason, effectiveness)
        if self._aborted:
            return await self._do_abort()

        # ---- EVALUATION ----
        await self._set_phase(Phase.EVALUATION)
        if self.state.real_outcome and self.state.twin_prediction:
            self.state.match_flag = (
                self.state.real_outcome == self.state.twin_prediction.predicted_outcome
            )
        await self._emit(
            "outcome",
            real_outcome=self.state.real_outcome.value if self.state.real_outcome else None,
            twin_outcome=(
                self.state.twin_prediction.predicted_outcome.value
                if self.state.twin_prediction
                else None
            ),
            match_flag=self.state.match_flag,
            principle=principle.value,
            rationale=(
                self.state.outcome_evaluation.rationale
                if self.state.outcome_evaluation
                else None
            ),
        )

        # ---- QUESTIONNAIRE ----
        if self.settings.questionnaire_enabled:
            await self._set_phase(Phase.QUESTIONNAIRE)
            await self._run_questionnaire()
            if self._aborted:
                return await self._do_abort()

        # ---- DEBRIEF ----
        await self._set_phase(Phase.DEBRIEF)
        await self._emit(
            "debrief",
            message=(
                "This conversation was part of a controlled academic research simulation. The "
                "scenario was fictional and harmless; no real credentials, links, or data were "
                "involved. Thank you for participating."
            ),
        )
        await self._set_phase(Phase.COMPLETE)
        await self._emit("complete", match_flag=self.state.match_flag)

    # ------------------------------------------------------------------ phase steps
    async def _process_profiling_turn(self, text: str) -> bool:
        state = self.state
        state.turn_count += 1
        state.conversation_history.append({"role": "user", "content": text})

        analysis = await self.loop.observe(state, text)
        trait_updates = self.loop.reason(state, analysis)
        for trait, delta in trait_updates.items():
            await self._emit("trait_update", trait=trait, delta=delta)

        complete, completion_reason = self.loop.validator.evaluate(state)
        state.profile_complete = complete
        state.completion_reason = str(completion_reason)

        # On the last profiling turn the scenario comes next, so don't ask a question that the
        # participant will never get an answer to.
        last_turn = (
            (complete and self.settings.stopping_rule)
            or state.turn_count >= self.settings.max_turns
            or self._finish_requested
        )
        reply = None
        if not last_turn:
            reply = await self._agent_reply(state)
            state.conversation_history.append({"role": "assistant", "content": reply})

        state.turn_logs.append(
            TurnLog(
                turn=state.turn_count,
                speaker="participant",
                message=text,
                signals_detected=[s["signal"] for s in analysis["signals"]],
                trait_updates=trait_updates,
                agent_action="continue_conversation",
                tone=analysis["tone"],
                engagement=analysis["engagement"],
                phase=Phase.PROFILING,
            )
        )
        if reply is not None:
            self.loop.log_agent_turn(state, reply, "continue_conversation")
        return complete

    async def _make_prediction(self, principle):
        # manual override takes priority if a readable file exists
        if self.settings.twin_enabled:
            manual = read_twin_prediction(self.settings.output_dir / "twin_prediction.txt")
            if manual:
                logger.info("using manual twin_prediction.txt override")
                return manual
            scenario_preview = await self.simulator.generate_scenario_message(self.state, principle)
            self.state.scenario_message = scenario_preview
            return await self.twin.predict(self.state, scenario_preview, principle)
        return read_twin_prediction(self.settings.output_dir / "twin_prediction.txt") or _default_prediction(principle)

    async def _run_simulation(self, principle, reason, effectiveness) -> None:
        state = self.state
        # reuse the scenario message the twin already saw, else generate fresh
        scenario = state.scenario_message or await self.simulator.generate_scenario_message(
            state, principle
        )
        state.scenario_message = scenario
        self.loop.log_agent_turn(state, scenario, f"run_scenario:{principle.value}")

        # Anything typed before the scenario message is shown is not a reply to it.
        self._drop_stale_messages()
        max_exchanges = max(1, self.settings.scenario_max_exchanges)
        sim_history: list[dict[str, str]] = []
        final_eval = None
        for exchange in range(max_exchanges):
            await self._emit(
                "scenario_message",
                message=scenario,
                principle=principle.value,
                reason=reason,
                exchange=exchange + 1,
                max_exchanges=max_exchanges,
            )
            sim_history.append({"role": "assistant", "content": scenario})

            await self._emit("await_message", context="scenario")
            msg = await self._next_input()
            if self._is_abort(msg):
                state.real_outcome = Outcome.INCOMPLETE
                return
            if msg["kind"] != "message":
                continue
            response = msg["text"].strip()
            await self._emit("participant_message", text=response)
            state.turn_count += 1
            state.conversation_history.append({"role": "user", "content": response})
            sim_history.append({"role": "user", "content": response})
            state.scenario_exchanges.append({"actor": scenario, "participant": response})

            final_eval = await self.evaluator.evaluate(state, scenario, response)
            state.turn_logs.append(
                TurnLog(
                    turn=state.turn_count,
                    speaker="participant",
                    message=response,
                    agent_action="scenario_response",
                    phase=Phase.SIMULATION,
                )
            )
            # stop early on a decisive outcome
            if final_eval.outcome in (Outcome.SUCCESS, Outcome.FAILURE):
                break
            if exchange < max_exchanges - 1:
                scenario = await self.simulator.generate_followup(state, principle, sim_history)

        state.outcome_evaluation = final_eval
        state.real_outcome = final_eval.outcome if final_eval else Outcome.INCOMPLETE

    async def _run_questionnaire(self) -> None:
        await self._emit(
            "await_questionnaire",
            items=questionnaire_items(),
            scale={str(i): lbl for i, lbl in _likert().items()},
        )
        msg = await self._next_input()
        if self._is_abort(msg):
            return
        responses = {}
        if msg["kind"] == "questionnaire":
            responses = msg.get("responses", {})
        result = score_responses(responses)
        self.state.questionnaire = result.to_dict()
        self.state.self_report_scores = result.scores_0_1
        comparison = self._compare_profiles(result.scores_0_1)
        await self._emit(
            "questionnaire_result",
            answered=result.answered,
            complete=result.complete,
            self_report_1_5=result.scores_1_5,
            comparison=comparison,
        )

    def _compare_profiles(self, self_report_0_1: dict[str, float]) -> dict:
        diffs = {}
        abs_errors = []
        for name, est in self.state.trait_estimates.items():
            if name in self_report_0_1:
                err = est.score - self_report_0_1[name]
                diffs[name] = {
                    "inferred": round(est.score, 3),
                    "self_report": round(self_report_0_1[name], 3),
                    "error": round(err, 3),
                }
                abs_errors.append(abs(err))
        mae = round(sum(abs_errors) / len(abs_errors), 3) if abs_errors else None
        result = {"per_trait": diffs, "mae": mae}
        self.state.self_report_scores = self_report_0_1
        return result

    # ------------------------------------------------------------------ agent output
    async def _agent_reply(self, state: AgentState) -> str:
        """Generate the agent's reply, streaming tokens when the provider supports it."""
        conv = self.loop.conversation
        steer, self._steer = self._steer, None  # researcher overrides apply to one reply
        auto_focus = conv.plan_focus(state)
        focus = (steer or {}).get("focus") or auto_focus
        note = (steer or {}).get("note")
        await self._emit(
            "agent_plan",
            turn=state.turn_count,
            focus=focus,
            auto_focus=auto_focus,
            note=note,
            steered=bool(steer),
        )
        parts: list[str] = []
        try:
            async for token in conv.stream_reply(state, focus, note):
                parts.append(token)
                await self._emit("agent_token", token=token)
        except Exception as exc:
            logger.debug("stream unavailable, falling back to full reply: {}", exc)
            parts = []
        text = "".join(parts) if parts else await conv.generate_reply(state, focus, note)
        await self._emit("agent_message", text=text)
        return text

    def _drop_stale_messages(self) -> None:
        kept = []
        while not self._input.empty():
            item = self._input.get_nowait()
            if item.get("kind") != "message":
                kept.append(item)
        for item in kept:
            self._input.put_nowait(item)

    def _is_abort(self, msg: dict) -> bool:
        return self._aborted or msg.get("kind") == "abort"

    async def _do_abort(self) -> None:
        self.state.aborted = True
        if self.state.real_outcome is None:
            self.state.real_outcome = Outcome.INCOMPLETE
        await self._set_phase(Phase.ABORTED)
        await self._emit("aborted")


def _new_session_id() -> str:
    return f"sess_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"


def _default_prediction(principle):
    from attack_agent.schemas import TwinPrediction

    return TwinPrediction(
        predicted_outcome=Outcome.PARTIAL,
        prediction_confidence=0.5,
        principles_used=[principle],
        reasoning="default placeholder prediction",
    )


def _likert():
    from attack_agent.data.ipip50 import LIKERT_LABELS

    return LIKERT_LABELS
