import asyncio
import sys

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from attack_agent.config import get_settings
from attack_agent.engine.evaluator import OutcomeEvaluator
from attack_agent.engine.llm import LLMClient, LLMError
from attack_agent.engine.simulator import ScenarioSimulator
from attack_agent.engine.strategy_selector import select_principle
from attack_agent.io.session_logger import write_session_log
from attack_agent.io.twin_reader import read_twin_prediction
from attack_agent.io.twin_writer import write_twin_data
from attack_agent.react.loop import ReActLoop
from datetime import datetime

from attack_agent.schemas import Outcome, Phase, StrategyPrinciple, TwinPrediction
from attack_agent.state import AgentState

console = Console()

BANNER = """[bold magenta]
 █████╗ ████████╗████████╗ █████╗  ██████╗██╗  ██╗    █████╗  ██████╗ ███████╗███╗   ██╗████████╗
██╔══██╗╚══██╔══╝╚══██╔══╝██╔══██╗██╔════╝██║  ██║   ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
███████║   ██║      ██║   ███████║██║     ███████║   ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
██╔══██║   ██║      ██║   ██╔══██║██║     ██╔══██║   ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
██║  ██║   ██║      ██║   ██║  ██║╚██████╗██║  ██║██╗██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
╚═╝  ╚═╝   ╚═╝      ╚═╝   ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝
[/bold magenta]
[dim]Conversational Profiling & Controlled Susceptibility Simulation — SE-AgentSim/EdgeClone[/dim]"""

CONSENT = """[bold yellow]ETHICS & CONSENT NOTICE[/bold yellow]
This is a [bold]controlled academic research simulation[/bold] (Final Year Project).
- The conversation is analyzed to build a personality profile.
- A [bold]harmless simulated scenario[/bold] (no credentials, no real links, no malware) may follow.
- All data stays local. You may quit anytime with [bold]/quit[/bold].
- A full session log is written to [bold]outputs/[/bold] for research analysis.
By continuing you consent to participate in this simulation study."""

HELP_TEXT = "[dim]Commands: /status (show profile) | /quit (end session)[/dim]"


def profile_panel(state: AgentState) -> Panel:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Trait", style="cyan", min_width=18)
    table.add_column("Score", min_width=8)
    table.add_column("Confidence", min_width=10)
    table.add_column("Evidence", min_width=8)
    for name, estimate in state.trait_estimates.items():
        bar = "█" * int(estimate.score * 10) + "░" * (10 - int(estimate.score * 10))
        table.add_row(
            name,
            f"{estimate.score:.2f} {bar}",
            f"{estimate.confidence:.2f}",
            str(estimate.evidence_count),
        )
    title = f"[bold]Big Five Profile[/bold] — turn {state.turn_count} | stability {state.profile_stability:.2f} | avg confidence {state.avg_confidence():.2f}"
    return Panel(table, title=title, border_style="dim")


async def healthcheck(llm: LLMClient) -> bool:
    try:
        models = await llm.list_models()
    except Exception as exc:
        console.print(
            Panel(
                "[bold red]Cannot reach Ollama.[/bold red]\n\n"
                "1. Install Ollama:\n   [cyan]curl -fsSL https://ollama.com/install.sh | sh[/cyan]\n"
                "2. Start the server:\n   [cyan]ollama serve[/cyan]\n"
                "3. Pull the model:\n   [cyan]ollama pull llama3.2:3b[/cyan]\n"
                "4. Re-run: [cyan]uv run attack-agent[/cyan]",
                title="Ollama not available",
                border_style="red",
            )
        )
        logger.error("ollama unreachable: {}", exc)
        return False
    model_name = get_settings().model_name
    if not any(model_name in name for name in models):
        console.print(
            Panel(
                f"[yellow]Model [bold]{model_name}[/bold] not found.[/yellow]\nRun: [cyan]ollama pull {model_name}[/cyan]",
                title="Model missing",
                border_style="yellow",
            )
        )
        return False
    return True


def get_user_input() -> str | None:
    try:
        return console.input("[bold cyan]You:[/bold cyan] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None


def request_twin_prediction(state: AgentState) -> TwinPrediction:
    settings = get_settings()
    prediction = read_twin_prediction(settings.output_dir / "twin_prediction.txt")
    if prediction:
        console.print(f"[green]Loaded twin prediction from outputs/twin_prediction.txt[/green]")
        return prediction

    console.print(
        Panel(
            "[yellow]outputs/twin_prediction.txt not found.[/yellow]\n\n"
            "For the demo you can create it manually (from your Digital Twin) or press [bold]Enter[/bold] to use a default placeholder prediction.\n\n"
            "[dim]Expected format:\nPREDICTED_OUTCOME: PARTIAL\nPREDICTION_CONFIDENCE: 0.78\nPRINCIPLES_USED: [\"authority\"]\nREASONING: why the twin predicts this[/dim]",
            title="Twin prediction",
            border_style="yellow",
        )
    )
    answer = console.input("[bold]Press Enter for default, or type 'wait' to create the file:[/bold] ").strip().lower()
    if answer == "wait":
        while True:
            console.input("[dim]Create outputs/twin_prediction.txt then press Enter...[/dim]")
            prediction = read_twin_prediction(settings.output_dir / "twin_prediction.txt")
            if prediction:
                return prediction
            console.print("[red]Still not found or unparseable. Try again.[/red]")
    console.print("[dim]Using default placeholder prediction (PARTIAL, authority).[/dim]")
    return TwinPrediction(
        predicted_outcome=Outcome.PARTIAL,
        prediction_confidence=0.6,
        principles_used=[StrategyPrinciple.AUTHORITY],
        reasoning="placeholder prediction (no Digital Twin connected yet)",
    )


async def run_session() -> None:
    settings = get_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(settings.log_dir / "attack_agent_{time}.log", rotation="10 MB", level="DEBUG")

    console.print(BANNER)
    console.print(Panel(CONSENT, border_style="yellow"))
    console.print(HELP_TEXT)

    llm = LLMClient(settings)
    if not await healthcheck(llm):
        sys.exit(1)

    session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    state = AgentState(session_id=session_id)
    state.init_traits()
    loop = ReActLoop(llm)

    console.print("\n[bold green]Profiling phase started. Chat naturally with Alex.[/bold green]\n")

    opening = await loop.conversation.generate_opening()
    console.print(f"[bold green]Alex:[/bold green] {opening}")
    loop.log_agent_turn(state, opening, "start_conversation")

    while state.phase == Phase.PROFILING:
        user_input = get_user_input()
        if user_input is None or user_input.lower() in ("/quit", "quit", "exit"):
            console.print("[yellow]Session ended by participant.[/yellow]")
            state.real_outcome = Outcome.INCOMPLETE
            log_path = write_session_log(state)
            console.print(f"[dim]Session log saved to {log_path}[/dim]")
            return
        if user_input.lower() == "/status":
            console.print(profile_panel(state))
            continue
        if not user_input:
            continue

        result = await loop.process_turn(state, user_input)
        console.print(f"[bold green]Alex:[/bold green] {result['agent_reply']}")
        loop.log_agent_turn(state, result["agent_reply"], "continue_conversation")
        console.print(profile_panel(state))

        if result["profile_complete"]:
            console.print(
                Panel(
                    f"[bold]Profile complete.[/bold]\n{result['completion_reason']}",
                    border_style="green",
                )
            )
            break

    loop.set_phase(state, Phase.TWIN_HANDOFF)
    twin_path = write_twin_data(state)
    state.twin_data_written = True
    console.print(Panel(f"[bold]twin_data.txt written:[/bold] {twin_path}\n[dim]This is the handoff artifact for the Digital Twin Generator.[/dim]", border_style="magenta"))

    state.twin_prediction = request_twin_prediction(state)

    principle, reason, predicted_effectiveness = select_principle(state, state.twin_prediction)
    state.current_principle = principle
    console.print(
        Panel(
            f"[bold]Scenario principle:[/bold] {principle.value}\n"
            f"[bold]Selection reason:[/bold] {reason}\n"
            f"[bold]Predicted effectiveness:[/bold] {predicted_effectiveness:.2f}\n"
            f"[bold]Twin predicted outcome:[/bold] {state.twin_prediction.predicted_outcome.value} "
            f"(confidence {state.twin_prediction.prediction_confidence:.2f})",
            title="Strategy selection",
            border_style="cyan",
        )
    )

    loop.set_phase(state, Phase.SIMULATION)
    simulator = ScenarioSimulator(llm)
    scenario_message = await simulator.generate_scenario_message(state, principle)
    state.scenario_message = scenario_message
    console.print("\n[bold red]── Controlled simulation scenario ──[/bold red]")
    console.print(Panel(scenario_message, title="Incoming message (simulated actor)", border_style="red"))
    loop.log_agent_turn(state, scenario_message, f"run_scenario:{principle.value}")
    console.print("[dim](Reply to the message above as you naturally would. /quit to abort.)[/dim]\n")

    response = get_user_input()
    if response is None or response.lower() in ("/quit", "quit", "exit"):
        state.real_outcome = Outcome.INCOMPLETE
        state.outcome_evaluation = None
    else:
        state.turn_count += 1
        state.conversation_history.append({"role": "user", "content": response})
        evaluator = OutcomeEvaluator(llm)
        evaluation = await evaluator.evaluate(state, scenario_message, response)
        state.outcome_evaluation = evaluation
        state.real_outcome = evaluation.outcome
        console.print(
            Panel(
                f"[bold]Outcome:[/bold] {evaluation.outcome.value}\n"
                f"[bold]Confidence:[/bold] {evaluation.confidence:.2f}\n"
                f"[bold]Rationale:[/bold] {evaluation.rationale}\n"
                + (
                    "[bold]Resistance:[/bold] "
                    + "; ".join(f"{s.signal_type} ({s.confidence:.2f})" for s in evaluation.resistance_signals)
                    if evaluation.resistance_signals
                    else "[bold]Resistance:[/bold] none detected"
                ),
                title="Outcome evaluation",
                border_style="blue",
            )
        )

    loop.set_phase(state, Phase.EVALUATION)
    if state.real_outcome and state.twin_prediction:
        state.match_flag = state.real_outcome == state.twin_prediction.predicted_outcome

    log_path = write_session_log(state)
    loop.set_phase(state, Phase.COMPLETE)

    summary = Table(show_header=True, header_style="bold")
    summary.add_column("Metric")
    summary.add_column("Value")
    summary.add_row("Session", state.session_id)
    summary.add_row("Turns", str(state.turn_count))
    summary.add_row("Principle used", state.current_principle.value if state.current_principle else "n/a")
    summary.add_row("Twin prediction", state.twin_prediction.predicted_outcome.value if state.twin_prediction else "n/a")
    summary.add_row("Real outcome", state.real_outcome.value if state.real_outcome else "n/a")
    summary.add_row(
        "Match flag",
        "[bold green]TRUE[/bold green]" if state.match_flag else "[bold red]FALSE[/bold red]",
    )
    console.print(Panel(summary, title="Session summary", border_style="magenta"))
    console.print(f"[dim]Session log: {log_path}[/dim]")

    console.print(
        Panel(
            "[bold]DEBRIEF:[/bold] This conversation was part of a controlled academic research simulation. "
            "The scenario was fictional and harmless; no real credentials or data were collected. "
            "Thank you for participating.",
            border_style="yellow",
        )
    )


def main() -> None:
    try:
        asyncio.run(run_session())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")


if __name__ == "__main__":
    main()