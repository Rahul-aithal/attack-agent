from attack_agent.engine.llm import LLMClient
from attack_agent.schemas import BehavioralEvidence

ANALYSIS_PROMPT = """You are a behavioral signal extractor for a research chat system.
Analyze the user message below for Big Five personality evidence.

USER MESSAGE:
{message}

RECENT CONVERSATION:
{history}

Rules:
- trait must be one of: openness, conscientiousness, extraversion, agreeableness, neuroticism
- direction "high" means the message suggests a higher level of that trait, "low" means lower
- evidence_strength between 0.0 and 1.0 (only include clear signals >= 0.4)
- do not invent evidence; if nothing clear, use empty signals list

Respond with ONLY this JSON:
{{"signals": [{{"trait": "...", "signal": "short label", "direction": "high", "evidence_strength": 0.7, "interpretation": "why"}}], "tone": "one or two words", "engagement": 0.0, "resistance": [{{"signal_type": "refusal|verification_request|suspicion|disengagement|hesitation", "confidence": 0.8, "description": "..."}}]}}"""

FALLBACK_KEYWORDS: dict[str, list[str]] = {
    "agreeableness": [
        "sure",
        "of course",
        "happy to",
        "no problem",
        "help",
        "glad",
        "thanks",
        "sorry",
    ],
    "conscientiousness": [
        "plan",
        "check",
        "verify",
        "organize",
        "deadline",
        "routine",
        "list",
        "schedule",
        "careful",
        "double-check",
    ],
    "openness": [
        "interesting",
        "curious",
        "wonder",
        "why",
        "how does",
        "new",
        "idea",
        "learn",
        "explore",
        "imagine",
    ],
    "extraversion": [
        "friends",
        "team",
        "we",
        "together",
        "party",
        "group",
        "people",
        "meet",
        "weekend",
    ],
    "neuroticism": [
        "worried",
        "stress",
        "anxious",
        "nervous",
        "panic",
        "afraid",
        "annoyed",
        "overwhelmed",
        "rushed",
    ],
}

POSITIVE_RESISTANCE_KEYWORDS = [
    "scam",
    "phishing",
    "fake",
    "suspicious",
    "is this real",
    "not comfortable",
    "no thanks",
    "refuse",
    "who are you",
    "how do i know",
    "prove",
    "legit",
    "verify you",
    "spam",
]


def keyword_fallback(user_message: str, turn: int) -> dict:
    text = user_message.lower()
    signals = []
    for trait, keywords in FALLBACK_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits >= 2:
            signals.append(
                {
                    "trait": trait,
                    "signal": f"keyword pattern: {trait}",
                    "direction": "high",
                    "evidence_strength": min(0.7, 0.45 + 0.1 * hits),
                    "interpretation": "detected via keyword fallback",
                }
            )
    engagement = min(1.0, len(user_message.split()) / 40)
    return {"signals": signals, "tone": "neutral", "engagement": engagement, "resistance": []}


def normalize_analysis(data: dict | None, user_message: str, turn: int) -> dict:
    if not isinstance(data, dict):
        return keyword_fallback(user_message, turn)
    signals = []
    for item in data.get("signals") or []:
        trait = item.get("trait")
        if trait not in (
            "openness",
            "conscientiousness",
            "extraversion",
            "agreeableness",
            "neuroticism",
        ):
            continue
        try:
            strength = float(item.get("evidence_strength", 0.5))
        except (TypeError, ValueError):
            strength = 0.5
        strength = min(1.0, max(0.0, strength))
        if strength < 0.4:
            continue
        signals.append(
            {
                "trait": trait,
                "signal": str(item.get("signal", "behavioral signal"))[:80],
                "direction": (
                    "low" if str(item.get("direction", "high")) == "low" else "high"
                ),
                "evidence_strength": strength,
                "interpretation": str(item.get("interpretation", ""))[:200],
            }
        )
    try:
        engagement = min(1.0, max(0.0, float(data.get("engagement", 0.5))))
    except (TypeError, ValueError):
        engagement = 0.5
    resistance = []
    for item in data.get("resistance") or []:
        if isinstance(item, dict) and item.get("signal_type"):
            resistance.append(
                {
                    "signal_type": str(item["signal_type"])[:40],
                    "confidence": min(1.0, max(0.0, float(item.get("confidence", 0.5)))),
                    "description": str(item.get("description", ""))[:160],
                }
            )
    return {
        "signals": signals,
        "tone": str(data.get("tone", "neutral"))[:30],
        "engagement": engagement,
        "resistance": resistance,
    }


class SignalExtractor:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def analyze(self, user_message: str, history: list[dict[str, str]], turn: int) -> dict:
        history_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Agent'}: {m['content']}"
            for m in history[-6:-1]
        )
        prompt = ANALYSIS_PROMPT.format(
            message=user_message, history=history_text or "(start of conversation)"
        )
        data = await self.llm.chat_json(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return normalize_analysis(data, user_message, turn)

    def to_evidence(self, analysis: dict, turn: int) -> list[BehavioralEvidence]:
        return [
            BehavioralEvidence(
                trait=signal["trait"],
                signal=signal["signal"],
                direction=signal["direction"],
                evidence_strength=signal["evidence_strength"],
                conversation_turn=turn,
                interpretation=signal["interpretation"],
            )
            for signal in analysis["signals"]
        ]

    def detect_resistance_keywords(self, text: str) -> list[dict]:
        lowered = text.lower()
        hits = [kw for kw in POSITIVE_RESISTANCE_KEYWORDS if kw in lowered]
        if not hits:
            return []
        return [
            {
                "signal_type": "resistance_keyword",
                "confidence": min(0.9, 0.5 + 0.1 * len(hits)),
                "description": f"matched: {', '.join(hits[:3])}",
            }
        ]
