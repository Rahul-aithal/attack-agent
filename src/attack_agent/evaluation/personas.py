"""Synthetic personas with KNOWN Big Five scores, used to measure profiling accuracy.

Each persona has ground-truth trait scores on the 0-1 scale. The ``sim_participant`` role is asked
to converse and answer the self-report questionnaire *in character*, so we can compare the agent's
inferred profile (and the persona's own questionnaire answers) against the known scores.
"""

from __future__ import annotations

from dataclasses import dataclass

from attack_agent.schemas import ALL_TRAITS


@dataclass
class Persona:
    id: str
    name: str
    traits: dict[str, float]  # 0-1 per trait
    blurb: str

    def trait_lines(self) -> str:
        labels = {0: "very low", 1: "low", 2: "moderate", 3: "high", 4: "very high"}
        out = []
        for t in ALL_TRAITS:
            v = self.traits[t]
            bucket = labels[min(4, int(v * 5))]
            out.append(f"  - {t}: {bucket}")
        return "\n".join(out)


def _p(o, c, e, a, n) -> dict[str, float]:
    return {
        "openness": o,
        "conscientiousness": c,
        "extraversion": e,
        "agreeableness": a,
        "neuroticism": n,
    }


PERSONAS: list[Persona] = [
    Persona("p_organizer", "Priya the organiser", _p(0.5, 0.9, 0.4, 0.6, 0.3),
            "methodical, plans everything, double-checks before acting, calm under pressure"),
    Persona("p_social", "Sam the socialite", _p(0.6, 0.4, 0.9, 0.7, 0.4),
            "outgoing, loves groups and parties, goes along with the crowd, spontaneous"),
    Persona("p_skeptic", "Riya the skeptic", _p(0.7, 0.7, 0.3, 0.3, 0.5),
            "questions everything, distrusts unsolicited requests, independent, blunt"),
    Persona("p_anxious", "Arjun the anxious", _p(0.5, 0.5, 0.4, 0.6, 0.9),
            "worries a lot, rattled by urgency and pressure, seeks reassurance"),
    Persona("p_explorer", "Mia the explorer", _p(0.95, 0.4, 0.6, 0.6, 0.4),
            "curious, loves new ideas and experiences, imaginative, open to novelty"),
    Persona("p_agreeable", "Leo the agreeable", _p(0.5, 0.6, 0.5, 0.95, 0.4),
            "warm, eager to help, avoids conflict, trusting and accommodating"),
    Persona("p_reserved", "Noor the reserved", _p(0.4, 0.6, 0.15, 0.5, 0.5),
            "quiet, keeps to themselves, few words, prefers solitude"),
    Persona("p_balanced", "Dev the balanced", _p(0.5, 0.5, 0.5, 0.5, 0.5),
            "unremarkable in every direction; a control persona near the midpoint"),
]

PERSONAS_BY_ID = {p.id: p for p in PERSONAS}
