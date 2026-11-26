"""Shared helpers for the analysis scripts. Pure-Python stats (no numpy dependency); matplotlib is
used only if installed and only for optional figures."""

from __future__ import annotations

import math
from pathlib import Path

from sqlmodel import Session as DBSession
from sqlmodel import select

from attack_agent.config import get_settings
from attack_agent.schemas import ALL_TRAITS
from attack_agent.storage.models import Participant, Questionnaire, Session, TraitSnapshot
from attack_agent.storage.repository import get_engine

OUTPUT = Path("outputs/analysis")


def _engine():
    return get_engine(get_settings())


def load_sessions() -> list[Session]:
    with DBSession(_engine()) as db:
        return list(db.exec(select(Session)).all())


def load_participants() -> dict[str, Participant]:
    with DBSession(_engine()) as db:
        return {p.id: p for p in db.exec(select(Participant)).all()}


def load_questionnaires() -> dict[str, Questionnaire]:
    with DBSession(_engine()) as db:
        return {q.session_id: q for q in db.exec(select(Questionnaire)).all()}


def load_trait_snapshots(session_id: str) -> list[TraitSnapshot]:
    with DBSession(_engine()) as db:
        return list(
            db.exec(select(TraitSnapshot).where(TraitSnapshot.session_id == session_id)).all()
        )


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


def mae(xs: list[float], ys: list[float]) -> float | None:
    if not xs:
        return None
    return round(sum(abs(x - y) for x, y in zip(xs, ys, strict=False)) / len(xs), 3)


def ensure_output() -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    return OUTPUT


def ground_truth(session: Session, participants: dict[str, Participant]) -> dict[str, float] | None:
    """Prefer known synthetic traits; fall back to the self-report questionnaire."""
    p = participants.get(session.participant_id or "")
    if p and p.known_traits:
        return p.known_traits
    if session.self_report_profile:
        return session.self_report_profile
    return None


__all__ = [
    "ALL_TRAITS",
    "ensure_output",
    "ground_truth",
    "load_participants",
    "load_questionnaires",
    "load_sessions",
    "load_trait_snapshots",
    "mae",
    "pearson",
]
