"""Session and study reports, written as Markdown from the SQLite store.

Markdown is the primary format (readable, diffable, easy to paste into the write-up). PDF is only
produced on request (``md_to_pdf``); the PDF library is imported lazily so nothing else depends
on it.
"""

from __future__ import annotations

import io
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlmodel import Session as DBSession
from sqlmodel import select

from attack_agent.config import Settings, get_settings
from attack_agent.schemas import ALL_TRAITS
from attack_agent.storage.models import LLMCall, Participant, Questionnaire, Session
from attack_agent.storage.repository import export_session, get_engine

ROLE_NAMES = {
    "agent": "chat agent",
    "extractor": "signal extractor",
    "twin": "digital twin",
    "judge": "judge",
    "sim_participant": "simulated participant",
}


# ----------------------------------------------------------------------------- helpers
def _to_1_5(x: float | None) -> float | None:
    return None if x is None else round(1 + 4 * x, 2)


def _fmt(x, nd: int = 2) -> str:
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _pct(n: int, d: int) -> str:
    return "–" if not d else f"{100 * n / d:.0f}% ({n}/{d})"


def _safe(text: str) -> str:
    """Participant/model text must not become HTML in the PDF renderer."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_escape(text: str) -> str:
    return _safe(text).replace("|", "\\|").replace("\n", " ")


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in _safe(text).splitlines())


def _dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return None if den == 0 else num / den


# ----------------------------------------------------------------------------- session
def session_report_md(session_id: str, settings: Settings | None = None) -> str | None:
    data = export_session(session_id, settings)
    if data is None:
        return None
    s = data["session"]
    cfg = s.get("config_snapshot") or {}
    started, ended = _dt(s.get("started_at")), _dt(s.get("ended_at"))
    duration = (
        f"{(ended - started).total_seconds() / 60:.1f} min" if started and ended else "–"
    )
    turns = data["turns"]
    participant_turns = [t for t in turns if t["speaker"] == "participant"]
    q = (data["questionnaires"] or [None])[0]
    pred = (data["predictions"] or [None])[0]
    outcome = (data["outcomes"] or [None])[0]

    out: list[str] = []
    out.append(f"# Session report — `{s['id']}`")
    out.append(f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_")
    out.append("")
    status = "aborted" if s.get("aborted") else s.get("phase", "")
    out.append("## Summary")
    out.append("")
    out.append("| Item | Value |")
    out.append("|---|---|")
    rows = [
        ("Status", status),
        ("Started", started.strftime("%Y-%m-%d %H:%M") if started else "–"),
        ("Duration", duration),
        ("Device", cfg.get("device") or "unknown"),
        ("Participant replies (chat + scenario)", len(participant_turns)),
        ("Profiling stop", _stop_reason(s)),
        ("Questionnaire answered", f"{q['answered']}/50" if q else "not taken"),
        ("Persuasion principle", s.get("principle") or "–"),
        ("Selection mode", s.get("selection_mode") or "–"),
        ("Twin prediction", s.get("twin_outcome") or "–"),
        ("Real outcome", s.get("real_outcome") or "–"),
        ("Match", {True: "**MATCH**", False: "**MISS**"}.get(s.get("match_flag"), "–")),
        ("Researcher steered", f"yes ({len(cfg.get('interventions') or [])} interventions)"
         if cfg.get("researcher_steered") else "no"),
    ]
    out += [f"| {k} | {_md_escape(str(v))} |" for k, v in rows]
    out.append("")

    # ---- profile
    inferred = s.get("inferred_profile") or {}
    conf = s.get("inferred_confidence") or {}
    self_rep = s.get("self_report_profile") or {}
    out.append("## Personality profile (Big Five, 1–5 scale)")
    out.append("")
    out.append("| Trait | Inferred | Confidence | Self-report | Error |")
    out.append("|---|---|---|---|---|")
    errs = []
    for t in ALL_TRAITS:
        inf, sr = inferred.get(t), self_rep.get(t)
        err = None if inf is None or sr is None else 4 * (inf - sr)
        if err is not None:
            errs.append(abs(err))
        out.append(
            f"| {t} | {_fmt(_to_1_5(inf))} | {_fmt(conf.get(t))} | {_fmt(_to_1_5(sr))} "
            f"| {'' if err is None else f'{err:+.2f}'} |"
        )
    if errs:
        out.append("")
        out.append(f"Mean absolute error (1–5 scale): **{sum(errs) / len(errs):.2f}**")
    out.append("")

    # ---- twin vs outcome
    out.append("## Digital twin vs real outcome")
    out.append("")
    twin = cfg.get("twin") or {}
    if pred:
        source = twin.get("source", "model")
        flag = "" if source in ("model", "manual") else f" — **{source}: not a real prediction**"
        out.append(
            f"**Twin predicted:** {pred['predicted_outcome']} "
            f"(agreement {pred['confidence']:.2f}){flag}"
        )
        if pred.get("reasoning"):
            out.append("")
            out.append(_quote(pred["reasoning"]))
        for i, x in enumerate(twin.get("samples") or [], 1):
            judged = "" if x.get("judged_by") == "model" else " (keyword rules)"
            out.append("")
            out.append(f"Simulation {i} → **{x.get('outcome')}**{judged}")
            out.append("")
            out.append(_quote(x.get("reply", "")))
    if outcome:
        out.append("")
        judged = " — judged by keyword rules (judge model unavailable)" if cfg.get(
            "judged_by") == "rules" else ""
        out.append(
            f"**Real outcome:** {outcome['outcome']} "
            f"(judge confidence {outcome['confidence']:.2f}){judged}"
        )
        if outcome.get("rationale"):
            out.append("")
            out.append(_quote(outcome["rationale"]))
        for sig in outcome.get("resistance_signals") or []:
            out.append(f"- resistance: {sig.get('signal_type')} — {sig.get('description', '')}")
    out.append("")

    # ---- evidence
    if data["evidence"]:
        out.append("## Strongest evidence")
        out.append("")
        out.append("| Turn | Trait | Dir | Strength | Signal |")
        out.append("|---|---|---|---|---|")
        top = sorted(data["evidence"], key=lambda e: e["evidence_strength"], reverse=True)[:12]
        for e in sorted(top, key=lambda e: e["conversation_turn"]):
            out.append(
                f"| {e['conversation_turn']} | {e['trait']} | {e['direction']} "
                f"| {e['evidence_strength']:.2f} | {_md_escape(e['signal'])} |"
            )
        out.append("")

    # ---- memory
    if cfg.get("memory"):
        out.append("## Question & answer memory")
        out.append("")
        out.append("| Turn | Topic | Question | Answer |")
        out.append("|---|---|---|---|")
        for m in cfg["memory"]:
            out.append(
                f"| {m.get('turn')} | {m.get('topic') or '–'} | {_md_escape(m.get('question', ''))} "
                f"| {_md_escape(m.get('answer', ''))} |"
            )
        out.append("")

    # ---- interventions
    if cfg.get("interventions"):
        out.append("## Researcher interventions")
        out.append("")
        for i in cfg["interventions"]:
            detail = ", ".join(i.get("focus") or []) or ""
            if i.get("note"):
                detail += f" “{i['note']}”"
            out.append(f"- turn {i.get('turn')} · {i.get('type')} {detail}".rstrip())
        out.append("")

    # ---- models
    if data["llm_calls"]:
        out.append("## Model calls")
        out.append("")
        out.append("| Role | Node / model | Calls | Avg latency | Failed |")
        out.append("|---|---|---|---|---|")
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for c in data["llm_calls"]:
            groups[(c["role"], c["node"], c["model"])].append(c)
        for (role, node, model), calls in sorted(groups.items()):
            avg = sum(c["latency_ms"] for c in calls) / len(calls) / 1000
            failed = sum(1 for c in calls if not c["ok"])
            out.append(
                f"| {ROLE_NAMES.get(role, role)} | {node}/{model} | {len(calls)} "
                f"| {avg:.1f} s | {failed} |"
            )
        out.append("")

    # ---- transcript
    out.append("## Transcript")
    out.append("")
    agent_sender = cfg.get("scenario_sender") == "agent"
    scenario_who = (
        "**Alex · the chat agent (simulated scenario)**"
        if agent_sender
        else "**Chris · IT Support (simulated scenario)**"
    )
    for t in turns:
        if t["speaker"] == "participant":
            who = "**Participant**"
        elif t["phase"] == "simulation":
            who = scenario_who
        else:
            who = "**Alex (agent)**"
        out.append(f"{who} — turn {t['turn']}")
        out.append("")
        out.append(_quote(t["message"]))
        out.append("")
    out.append("---")
    out.append(
        "_Controlled academic research simulation. The scenario was fictional and harmless; no "
        "real credentials, links or payment details were involved._"
    )
    return "\n".join(out) + "\n"


def _stop_reason(s: dict) -> str:
    reason = s.get("completion_reason") or ""
    if "'forced_by_max_turns': True" in reason:
        return "max turns reached"
    if "'turns_ok': True" in reason:
        return "profile confident"
    return "ended early" if s.get("turn_count") else "–"


# ----------------------------------------------------------------------------- study
def study_report_md(settings: Settings | None = None, include_synthetic: bool = False) -> str:
    settings = settings or get_settings()
    with DBSession(get_engine(settings)) as db:
        sessions = list(db.exec(select(Session)).all())
        participants = {p.id: p for p in db.exec(select(Participant)).all()}
        questionnaires = {q.session_id: q for q in db.exec(select(Questionnaire)).all()}
        calls = list(db.exec(select(LLMCall)).all())

    def synthetic(s: Session) -> bool:
        p = participants.get(s.participant_id or "")
        return bool(p and p.is_synthetic)

    pool = [s for s in sessions if include_synthetic or not synthetic(s)]
    # A session counts once the scenario was answered, even if the participant left during the
    # questionnaire afterwards (aborted then only means "no self-report").
    done = [s for s in pool if s.real_outcome and s.real_outcome != "INCOMPLETE"]
    steered = [s for s in pool if (s.config_snapshot or {}).get("researcher_steered")]
    unsteered_done = [s for s in done if s not in steered]

    out: list[str] = []
    out.append("# Study report")
    out.append(
        f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} from "
        f"`{settings.database_url}`_"
    )
    out.append("")
    out.append("## Sessions")
    out.append("")
    out.append("| Item | Value |")
    out.append("|---|---|")
    devices = Counter((s.config_snapshot or {}).get("device") or "unknown" for s in pool)
    out += [
        f"| Sessions{' (incl. synthetic)' if include_synthetic else ' (real participants)'} "
        f"| {len(pool)} |",
        f"| Completed with an outcome | {len(done)} |",
        f"| Left before the scenario was answered | "
        f"{sum(1 for s in pool if s.real_outcome in (None, 'INCOMPLETE'))} |",
        f"| Steered by researcher | {len(steered)} |",
        f"| Questionnaire complete | "
        f"{sum(1 for s in pool if (q := questionnaires.get(s.id)) and q.complete)} |",
        f"| Devices | {', '.join(f'{k}: {v}' for k, v in devices.most_common())} |",
    ]
    if done:
        out.append(f"| Mean participant turns | {sum(s.turn_count for s in done) / len(done):.1f} |")
    out.append("")
    if steered:
        out.append(
            f"> {len(steered)} session(s) were steered by the researcher. Headline figures below "
            "use **unsteered** sessions only; steered ones are listed separately."
        )
        out.append("")

    basis = unsteered_done
    out.append("## Twin prediction accuracy")
    out.append("")
    matched = [s for s in basis if s.match_flag is not None]
    out.append(f"Overall match rate: **{_pct(sum(1 for s in matched if s.match_flag), len(matched))}**")
    no_pred = sum(1 for s in basis if s.match_flag is None)
    rules = sum(1 for s in basis if (s.config_snapshot or {}).get("judged_by") == "rules")
    if no_pred or rules:
        out.append("")
        out.append(
            f"> Data quality: {no_pred} completed session(s) had no real twin prediction "
            f"(twin unavailable; excluded from the match rate) and {rules} real outcome(s) were "
            "classified by keyword rules because the judge model was unavailable."
        )
    out.append("")
    out.append("| Group | Match rate |")
    out.append("|---|---|")
    for label, key in (("principle", "principle"), ("selection mode", "selection_mode")):
        groups: dict[str, list[Session]] = defaultdict(list)
        for s in matched:
            groups[getattr(s, key) or "–"].append(s)
        for g, items in sorted(groups.items()):
            out.append(f"| {label}: {g} | {_pct(sum(1 for s in items if s.match_flag), len(items))} |")
    out.append("")

    out.append("## Real outcomes")
    out.append("")
    out.append("| Principle | SUCCESS | PARTIAL | FAILURE |")
    out.append("|---|---|---|---|")
    by_principle: dict[str, Counter] = defaultdict(Counter)
    for s in basis:
        by_principle[s.principle or "–"][s.real_outcome] += 1
    for p, c in sorted(by_principle.items()):
        out.append(f"| {p} | {c['SUCCESS']} | {c['PARTIAL']} | {c['FAILURE']} |")
    out.append("")

    out.append("## Profiling accuracy (inferred vs self-report, 1–5 scale)")
    out.append("")
    out.append("| Trait | n | MAE | Pearson r |")
    out.append("|---|---|---|---|")
    for t in ALL_TRAITS:
        xs, ys = [], []
        for s in basis:
            inf, sr = (s.inferred_profile or {}).get(t), (s.self_report_profile or {}).get(t)
            if inf is not None and sr is not None:
                xs.append(1 + 4 * inf)
                ys.append(1 + 4 * sr)
        mae = sum(abs(a - b) for a, b in zip(xs, ys, strict=True)) / len(xs) if xs else None
        out.append(f"| {t} | {len(xs)} | {_fmt(mae)} | {_fmt(_pearson(xs, ys))} |")
    out.append("")
    out.append("_Pearson r needs at least 3 sessions; with small n treat all figures as indicative._")
    out.append("")

    if calls:
        out.append("## Model performance")
        out.append("")
        out.append("| Role | Node / model | Calls | Avg latency | Failure rate |")
        out.append("|---|---|---|---|---|")
        groups2: dict[tuple, list[LLMCall]] = defaultdict(list)
        for c in calls:
            groups2[(c.role, c.node, c.model)].append(c)
        for (role, node, model), items in sorted(groups2.items()):
            avg = sum(c.latency_ms for c in items) / len(items) / 1000
            fail = sum(1 for c in items if not c.ok)
            out.append(
                f"| {ROLE_NAMES.get(role, role)} | {node}/{model} | {len(items)} | {avg:.1f} s "
                f"| {_pct(fail, len(items))} |"
            )
        out.append("")

    out.append("## All sessions")
    out.append("")
    out.append("| Session | Start | Turns | Principle | Twin | Real | Match | Device | Steered |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for s in sorted(pool, key=lambda s: s.started_at):
        cfg = s.config_snapshot or {}
        match = {True: "yes", False: "no"}.get(s.match_flag, "–")
        out.append(
            f"| `{s.id[-12:]}` | {s.started_at.strftime('%m-%d %H:%M')} | {s.turn_count} "
            f"| {s.principle or '–'} | {s.twin_outcome or '–'} "
            f"| {'aborted' if s.aborted else s.real_outcome or '–'} "
            f"| {match} "
            f"| {cfg.get('device') or '–'} | {'yes' if cfg.get('researcher_steered') else ''} |"
        )
    out.append("")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- pdf
def md_to_pdf(markdown: str, title: str = "Attack Agent report") -> bytes:
    """Convert a Markdown report to PDF (only called when a PDF is explicitly requested)."""
    from markdown_pdf import MarkdownPdf, Section

    pdf = MarkdownPdf(toc_level=2, optimize=True)  # tables are enabled by markdown-pdf itself
    pdf.meta["title"] = title
    css = (
        "body { font-family: sans-serif; font-size: 10pt; } "
        "table { border-collapse: collapse; } th, td { border: 1px solid #999; padding: 2px 4px; } "
        "blockquote { color: #333; margin-left: 8px; }"
    )
    pdf.add_section(Section(markdown, paper_size="A4"), user_css=css)
    buf = io.BytesIO()
    pdf.save_bytes(buf)
    return buf.getvalue()
