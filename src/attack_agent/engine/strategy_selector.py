"""Strategy selection: map the inferred profile to a persuasion principle.

Selection modes (``Settings.selection_mode``) support controlled experiments:
  - ``literature_map``  : trait -> principle table from config/strategy_map.yaml (default)
  - ``twin_driven``     : use the principle the digital twin recommends, else fall back to the map
  - ``random``          : uniform random principle (control condition)
  - ``fixed:<principle>``: always the named principle (e.g. ``fixed:authority``)
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

import yaml
from loguru import logger

from attack_agent.config import Settings, get_settings
from attack_agent.schemas import StrategyPrinciple, TwinPrediction
from attack_agent.state import AgentState


@dataclass
class StrategyRow:
    trait: str
    principle: StrategyPrinciple
    min_score: float
    rationale: str
    citation: str


@dataclass
class StrategyMap:
    rows: list[StrategyRow]
    default_principle: StrategyPrinciple


@lru_cache
def load_strategy_map(path: str | None = None) -> StrategyMap:
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("attack_agent.config_data").joinpath("strategy_map.yaml").read_text(
            encoding="utf-8"
        )
    data = yaml.safe_load(text) or {}
    rows = [
        StrategyRow(
            trait=str(r["trait"]),
            principle=StrategyPrinciple(str(r["principle"])),
            min_score=float(r.get("min_score", 0.55)),
            rationale=str(r.get("rationale", "")),
            citation=str(r.get("citation", "")),
        )
        for r in (data.get("rows") or [])
    ]
    default = StrategyPrinciple(str(data.get("default_principle", "authority")))
    return StrategyMap(rows=rows, default_principle=default)


def _from_map(state: AgentState, smap: StrategyMap) -> tuple[StrategyPrinciple, str, float]:
    ranked = sorted(state.trait_estimates.items(), key=lambda kv: kv[1].score, reverse=True)
    if not ranked:
        return smap.default_principle, "no trait estimates; default principle", 0.5
    top_trait, top = ranked[0]
    for row in smap.rows:
        if row.trait == top_trait and top.score >= row.min_score:
            confidence = min(0.9, 0.5 + 0.4 * top.score * top.confidence)
            reason = f"literature_map: {row.rationale} [{row.citation}]"
            return row.principle, reason, confidence
    return smap.default_principle, "literature_map: no dominant trait above threshold", 0.5


def select_principle(
    state: AgentState,
    prediction: TwinPrediction | None,
    settings: Settings | None = None,
) -> tuple[StrategyPrinciple, str, float]:
    settings = settings or get_settings()
    mode = settings.selection_mode
    map_path = str(settings.strategy_map_file) if settings.strategy_map_file else None
    smap = load_strategy_map(map_path)

    if mode.startswith("fixed:"):
        name = mode.split(":", 1)[1].strip()
        try:
            return StrategyPrinciple(name), f"fixed selection: {name}", 0.5
        except ValueError:
            logger.warning("invalid fixed principle '{}', using default", name)
            return smap.default_principle, "fixed selection invalid; default", 0.5

    if mode == "random":
        principle = random.choice(list(StrategyPrinciple))
        return principle, "random selection (control condition)", 0.5

    if mode == "twin_driven":
        if prediction and prediction.principles_used:
            return (
                prediction.principles_used[0],
                "twin_driven: principle recommended by digital twin",
                prediction.prediction_confidence,
            )
        return _from_map(state, smap)

    # default: literature_map
    return _from_map(state, smap)


# Backwards-compatible view of the mapping for tests / introspection.
TRAIT_PRINCIPLE_MAP = [
    (row.trait, row.principle, row.rationale) for row in load_strategy_map().rows
]
