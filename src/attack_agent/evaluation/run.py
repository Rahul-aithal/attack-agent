"""Evaluation runner: drive full sessions with synthetic participants and store the results.

Each run pairs a ``SessionEngine`` (the system under test) with a ``SimParticipant`` (a persona
played by the ``sim_participant`` role on a different model family). The driver consumes engine
events and feeds back in-character replies and questionnaire answers, then persists the session so
the analysis scripts can compute accuracy, calibration and twin-match metrics from SQLite.

Usage:
    attack-agent-eval --personas all --repeats 3 --experiment accuracy
    attack-agent-eval --persona p_skeptic --selection-mode fixed:authority
"""

from __future__ import annotations

import argparse
import asyncio

from loguru import logger

from attack_agent.config import Settings, get_settings
from attack_agent.engine.llm import RoleClient, Router, current_session_id
from attack_agent.engine.session_engine import SessionEngine
from attack_agent.evaluation.personas import PERSONAS, PERSONAS_BY_ID, Persona
from attack_agent.evaluation.sim_participant import SimParticipant
from attack_agent.storage import ensure_participant, persist_session


async def run_one(
    persona: Persona,
    router: Router,
    settings: Settings,
    experiment_id: str | None = None,
) -> dict:
    engine = SessionEngine(router, settings=settings)
    sim = SimParticipant(RoleClient(router, "sim_participant"), persona)
    token = current_session_id.set(engine.session_id)
    try:
        async for event in engine.events():
            etype = event.get("type")
            if etype == "await_message":
                reply = await sim.reply(engine.state.conversation_history)
                engine.submit_message(reply)
            elif etype == "await_questionnaire":
                engine.submit_questionnaire(await sim.answer_questionnaire())
            elif etype == "error":
                logger.error("engine error: {}", event.get("message"))
    finally:
        current_session_id.reset(token)

    state = engine.state
    participant_id = f"sim_{persona.id}"
    ensure_participant(
        participant_id, label=persona.name, is_synthetic=True,
        known_traits=persona.traits, settings=settings,
    )
    persist_session(
        state,
        participant_id=participant_id,
        experiment_id=experiment_id,
        llm_calls=router.calls,
        config_snapshot={
            "selection_mode": settings.selection_mode,
            "profiler_version": settings.profiler_version,
            "extractor_mode": settings.extractor_mode,
            "stopping_rule": settings.stopping_rule,
            "known_traits": persona.traits,
        },
        settings=settings,
    )
    router.calls.clear()
    mae = None
    if state.self_report_scores:
        errs = [abs(state.trait_estimates[t].score - v) for t, v in persona.traits.items()]
        mae = round(sum(errs) / len(errs), 3)
    logger.info(
        "session {} persona={} outcome={} match={} turns={}",
        state.session_id, persona.id, state.real_outcome, state.match_flag, state.turn_count,
    )
    return {
        "session_id": state.session_id,
        "persona": persona.id,
        "inferred_mae_vs_known": mae,
        "outcome": state.real_outcome.value if state.real_outcome else None,
        "match_flag": state.match_flag,
    }


async def run_batch(args: argparse.Namespace) -> list[dict]:
    overrides = {}
    if args.selection_mode:
        overrides["selection_mode"] = args.selection_mode
    if args.profiler:
        overrides["profiler_version"] = args.profiler
    if args.extractor:
        overrides["extractor_mode"] = args.extractor
    if args.no_stopping_rule:
        overrides["stopping_rule"] = False
    settings = Settings(**{**get_settings().model_dump(), **overrides})

    router = Router.from_settings(settings)
    if args.persona:
        personas = [PERSONAS_BY_ID[args.persona]]
    else:
        personas = PERSONAS
    results = []
    try:
        for _ in range(args.repeats):
            for persona in personas:
                results.append(
                    await run_one(persona, router, settings, experiment_id=args.experiment)
                )
    finally:
        await router.aclose()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic-participant evaluation sessions.")
    parser.add_argument("--persona", choices=list(PERSONAS_BY_ID), help="single persona id")
    parser.add_argument("--personas", default="all", help="'all' (default)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--experiment", default=None, help="experiment/tag id stored with sessions")
    parser.add_argument("--selection-mode", default=None)
    parser.add_argument("--profiler", choices=["beta", "v1"], default=None)
    parser.add_argument("--extractor", choices=["llm", "keyword"], default=None)
    parser.add_argument("--no-stopping-rule", action="store_true")
    args = parser.parse_args()

    results = asyncio.run(run_batch(args))
    ok = sum(1 for r in results if r["outcome"])
    print(f"\nCompleted {len(results)} sessions ({ok} with an outcome).")
    maes = [r["inferred_mae_vs_known"] for r in results if r["inferred_mae_vs_known"] is not None]
    if maes:
        print(f"Mean inferred-vs-known MAE: {sum(maes) / len(maes):.3f}")
    print("Run analysis with: uv run python -m analysis.accuracy")


if __name__ == "__main__":
    main()
