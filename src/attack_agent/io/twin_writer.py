from datetime import datetime, timezone
from pathlib import Path

from attack_agent.config import get_settings
from attack_agent.state import AgentState


def communication_style_lines(state: AgentState) -> list[str]:
    participant_logs = [log for log in state.turn_logs if log.speaker == "participant"]
    tones = [log.tone for log in participant_logs if log.tone]
    tone = max(set(tones), key=tones.count) if tones else "unknown"
    avg_engagement = (
        sum(log.engagement for log in participant_logs) / len(participant_logs)
        if participant_logs
        else 0.0
    )
    engagement_label = (
        "high" if avg_engagement >= 0.6 else "medium" if avg_engagement >= 0.35 else "low"
    )
    avg_words = (
        sum(len(log.message.split()) for log in participant_logs) / len(participant_logs)
        if participant_logs
        else 0
    )
    length_label = "long" if avg_words > 25 else "medium" if avg_words > 10 else "short"
    return [
        f"  formality: {tone}",
        f"  engagement: {engagement_label} ({avg_engagement:.2f})",
        f"  response_length: {length_label} (avg {avg_words:.0f} words)",
    ]


def behavioral_summary(state: AgentState) -> list[str]:
    summary: list[str] = []
    for estimate in sorted(
        state.trait_estimates.values(), key=lambda e: e.score, reverse=True
    ):
        if estimate.evidence_count == 0:
            continue
        strongest = max(
            (ev for ev in state.evidence if ev.trait == estimate.trait),
            key=lambda ev: ev.evidence_strength,
            default=None,
        )
        level = (
            "high" if estimate.score >= 0.65 else "moderate" if estimate.score >= 0.45 else "low"
        )
        line = f"  - {estimate.trait}: {level} ({estimate.score:.2f}, confidence {estimate.confidence:.2f}, {estimate.evidence_count} evidence items)"
        if strongest:
            line += f" — e.g. [{strongest.signal}]"
        summary.append(line)
    return summary or ["  - insufficient evidence collected"]


def write_twin_data(state: AgentState, output_dir=None) -> Path:
    settings = get_settings()
    output_dir = Path(output_dir) if output_dir else settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "twin_data.txt"

    lines = [
        "=" * 64,
        "DIGITAL TWIN HANDOFF DATA — EDGECLONE ATTACK AGENT",
        "=" * 64,
        f"SESSION_ID: {state.session_id}",
        f"TIMESTAMP: {datetime.now(timezone.utc).isoformat()}",
        f"CONVERSATION_TURNS: {state.turn_count}",
        f"PROFILE_STABILITY: {state.profile_stability:.3f}",
        f"AVG_TRAIT_CONFIDENCE: {state.avg_confidence():.3f}",
        f"COMPLETION_REASON: {state.completion_reason or 'n/a'}",
        "",
        "BIG_FIVE:",
    ]
    for name, estimate in state.trait_estimates.items():
        lines.append(
            f"  {name}: score={estimate.score:.2f} confidence={estimate.confidence:.2f} "
            f"evidence_count={estimate.evidence_count} last_updated_turn={estimate.last_updated_turn}"
        )
    lines += ["", "COMMUNICATION_STYLE:", *communication_style_lines(state)]
    lines += ["", "BEHAVIORAL_SUMMARY:", *behavioral_summary(state)]
    lines += ["", "BEHAVIORAL_EVIDENCE_LOG:"]
    if state.evidence:
        for ev in state.evidence:
            lines.append(
                f"  [turn {ev.conversation_turn}] {ev.trait} ({ev.direction}) "
                f"strength={ev.evidence_strength:.2f} :: {ev.signal}"
                + (f" — {ev.interpretation}" if ev.interpretation else "")
            )
    else:
        lines.append("  (none)")
    lines += [
        "",
        "-" * 64,
        "TWIN_HANDOFF_NOTE: Feed the BIG_FIVE scores, confidences, communication",
        "style and behavioral summary above to the Digital Twin Generator as",
        "persona context. The Digital Twin should then be asked how it would",
        "respond to a scenario message, producing outputs/twin_prediction.txt.",
        "-" * 64,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
