"""Developer CLI: a thin client over SessionEngine. The web UI is the primary deliverable; this
stays as a quick local driver for one interactive session."""

from __future__ import annotations

import asyncio
import sys

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from attack_agent.config import get_settings
from attack_agent.engine.llm import Router
from attack_agent.engine.session_engine import SessionEngine
from attack_agent.storage import persist_session

console = Console()

BANNER = "[bold magenta]ATTACK AGENT[/bold magenta] — Conversational Profiling & Controlled Susceptibility Simulation"

CONSENT = """[bold yellow]ETHICS & CONSENT NOTICE[/bold yellow]
This is a [bold]controlled academic research simulation[/bold] (Final Year Project).
- The chat is casual but personal — everyday topics like free time, friendships, feelings and how you
  handle stress — and it is analysed to build a personality profile.
- At some point a [bold]harmless simulated request[/bold] may be made of you — as a message from a new simulated
  contact (e.g., "IT Support") or from the agent itself. No real credentials, links, or payments are involved.
- A short personality questionnaire is given afterwards.
- All data stays local. You may quit anytime with [bold]/quit[/bold].
By continuing you consent to participate, and you agree that such a simulated request may be made of you."""


def profile_panel(state) -> Panel:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Trait", style="cyan", min_width=18)
    table.add_column("Score", min_width=16)
    table.add_column("Conf", min_width=6)
    table.add_column("Ev", min_width=4)
    for name, est in state.trait_estimates.items():
        filled = int(est.score * 10)
        bar = "█" * filled + "░" * (10 - filled)
        table.add_row(name, f"{est.score:.2f} {bar}", f"{est.confidence:.2f}", str(est.evidence_count))
    title = (
        f"Big Five — turn {state.turn_count} | stability {state.profile_stability:.2f}"
        f" | avg conf {state.avg_confidence():.2f}"
    )
    return Panel(table, title=title, border_style="dim")


async def _check_router(router: Router) -> bool:
    status = await router.status()
    healthy = [n for n in status if n["healthy"]]
    if not healthy:
        console.print(
            Panel(
                "[bold red]No model node is reachable.[/bold red]\n\n"
                "Single machine: start Ollama and pull a model:\n"
                "  [cyan]bash scripts/install_ollama.sh[/cyan]\n\n"
                "Multi-machine: check deploy.yaml node URLs and that each Ollama is bound to\n"
                "the network ([cyan]OLLAMA_HOST=0.0.0.0 ollama serve[/cyan]).",
                title="No nodes available",
                border_style="red",
            )
        )
        return False
    console.print(f"[dim]Nodes up: {', '.join(n['node'] for n in healthy)}[/dim]")
    return True


def _read_input() -> str | None:
    try:
        return console.input("[bold cyan]You:[/bold cyan] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _ask_questionnaire(items: list[dict]) -> dict[int, int]:
    console.print(
        Panel(
            "Rate each statement 1-5 (1=very inaccurate, 5=very accurate). "
            "Press Enter to skip an item (counts as neutral 3).",
            title="Personality questionnaire (IPIP-50)",
            border_style="cyan",
        )
    )
    responses: dict[int, int] = {}
    for item in items:
        while True:
            raw = console.input(f"[cyan]{item['id']:>2}.[/cyan] I {item['text']} ").strip()
            if not raw:
                break
            if raw.isdigit() and 1 <= int(raw) <= 5:
                responses[item["id"]] = int(raw)
                break
            console.print("[red]Enter 1-5 or press Enter to skip.[/red]")
    return responses


async def run_session() -> None:
    settings = get_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(settings.log_dir / "attack_agent_{time}.log", rotation="10 MB", level="DEBUG")

    console.print(Panel(BANNER, border_style="magenta"))
    console.print(Panel(CONSENT, border_style="yellow"))

    router = Router.from_settings(settings)
    if not await _check_router(router):
        await router.aclose()
        sys.exit(1)

    engine = SessionEngine(router, settings=settings)
    pending_questionnaire: list[dict] = []

    try:
        async for event in engine.events():
            etype = event["type"]
            if etype == "phase_change":
                console.print(f"[dim]— phase: {event['phase']} —[/dim]")
            elif etype == "agent_message":
                console.print(f"[bold green]Alex:[/bold green] {event['text']}")
            elif etype == "profile":
                console.print(profile_panel(engine.state))
            elif etype == "await_message":
                if event.get("context") == "scenario":
                    console.print("[dim](reply to the message above; /quit to abort)[/dim]")
                text = _read_input()
                if text is None or text.lower() in ("/quit", "quit", "exit"):
                    engine.abort()
                elif text.lower() == "/status":
                    console.print(profile_panel(engine.state))
                    engine.submit_message("")  # no-op; re-prompt
                else:
                    engine.submit_message(text)
            elif etype == "scenario_message":
                console.print(
                    Panel(
                        event["message"],
                        title=f"Incoming message — principle: {event['principle']}",
                        border_style="red",
                    )
                )
            elif etype == "twin_prediction":
                console.print(
                    Panel(
                        f"predicted: {event['predicted_outcome']} "
                        f"(conf {event['confidence']:.2f})\n{event['reasoning']}",
                        title="Digital twin prediction",
                        border_style="cyan",
                    )
                )
            elif etype == "outcome":
                match = event.get("match_flag")
                color = "green" if match else "red"
                console.print(
                    Panel(
                        f"real outcome: [bold]{event.get('real_outcome')}[/bold]\n"
                        f"twin predicted: {event.get('twin_outcome')}\n"
                        f"match: [bold {color}]{match}[/bold {color}]",
                        title="Outcome",
                        border_style="blue",
                    )
                )
            elif etype == "await_questionnaire":
                pending_questionnaire = event["items"]
                engine.submit_questionnaire(_ask_questionnaire(pending_questionnaire))
            elif etype == "questionnaire_result":
                comp = event.get("comparison") or {}
                console.print(
                    Panel(
                        f"answered {event['answered']}/50 — inferred-vs-self-report "
                        f"MAE: {comp.get('mae')}",
                        title="Self-report comparison",
                        border_style="cyan",
                    )
                )
            elif etype == "debrief":
                console.print(Panel(event["message"], title="Debrief", border_style="yellow"))
            elif etype == "aborted":
                console.print("[yellow]Session aborted.[/yellow]")
            elif etype == "error":
                console.print(f"[red]Error: {event['message']}[/red]")
    finally:
        try:
            persist_session(engine.state, llm_calls=router.calls, settings=settings)
            console.print(f"[dim]Saved to database ({settings.database_url}).[/dim]")
        except Exception as exc:
            logger.warning("persist failed: {}", exc)
        await router.aclose()


def main() -> None:
    try:
        asyncio.run(run_session())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")


if __name__ == "__main__":
    main()
