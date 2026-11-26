"""IPIP-50 Big Five markers (International Personality Item Pool, public domain).

Source: Goldberg, L. R. (1992), via the International Personality Item Pool (https://ipip.ori.org/).
These 50 items are public domain and may be used without permission. Each item is answered on a
1-5 Likert scale (1 = Very inaccurate, 5 = Very accurate). Ten items per trait; items keyed "-"
are reverse-scored (6 - raw). The mean of a trait's ten (keyed) items gives a 1-5 trait score,
which is the ground-truth self-report compared against the agent's inferred score.
"""

from __future__ import annotations

from dataclasses import dataclass

LIKERT_MIN = 1
LIKERT_MAX = 5

LIKERT_LABELS = {
    1: "Very inaccurate",
    2: "Moderately inaccurate",
    3: "Neither accurate nor inaccurate",
    4: "Moderately accurate",
    5: "Very accurate",
}


@dataclass(frozen=True)
class IPIPItem:
    id: int
    text: str
    trait: str  # openness | conscientiousness | extraversion | agreeableness | neuroticism
    keyed: str  # "+" or "-"


# "I ..." stem; items as commonly worded in the IPIP 50-item Big-Five set.
IPIP50: list[IPIPItem] = [
    IPIPItem(1, "Am the life of the party.", "extraversion", "+"),
    IPIPItem(2, "Feel little concern for others.", "agreeableness", "-"),
    IPIPItem(3, "Am always prepared.", "conscientiousness", "+"),
    IPIPItem(4, "Get stressed out easily.", "neuroticism", "+"),
    IPIPItem(5, "Have a rich vocabulary.", "openness", "+"),
    IPIPItem(6, "Don't talk a lot.", "extraversion", "-"),
    IPIPItem(7, "Am interested in people.", "agreeableness", "+"),
    IPIPItem(8, "Leave my belongings around.", "conscientiousness", "-"),
    IPIPItem(9, "Am relaxed most of the time.", "neuroticism", "-"),
    IPIPItem(10, "Have difficulty understanding abstract ideas.", "openness", "-"),
    IPIPItem(11, "Feel comfortable around people.", "extraversion", "+"),
    IPIPItem(12, "Insult people.", "agreeableness", "-"),
    IPIPItem(13, "Pay attention to details.", "conscientiousness", "+"),
    IPIPItem(14, "Worry about things.", "neuroticism", "+"),
    IPIPItem(15, "Have a vivid imagination.", "openness", "+"),
    IPIPItem(16, "Keep in the background.", "extraversion", "-"),
    IPIPItem(17, "Sympathize with others' feelings.", "agreeableness", "+"),
    IPIPItem(18, "Make a mess of things.", "conscientiousness", "-"),
    IPIPItem(19, "Seldom feel blue.", "neuroticism", "-"),
    IPIPItem(20, "Am not interested in abstract ideas.", "openness", "-"),
    IPIPItem(21, "Start conversations.", "extraversion", "+"),
    IPIPItem(22, "Am not interested in other people's problems.", "agreeableness", "-"),
    IPIPItem(23, "Get chores done right away.", "conscientiousness", "+"),
    IPIPItem(24, "Am easily disturbed.", "neuroticism", "+"),
    IPIPItem(25, "Have excellent ideas.", "openness", "+"),
    IPIPItem(26, "Have little to say.", "extraversion", "-"),
    IPIPItem(27, "Have a soft heart.", "agreeableness", "+"),
    IPIPItem(28, "Often forget to put things back in their proper place.", "conscientiousness", "-"),
    IPIPItem(29, "Get upset easily.", "neuroticism", "+"),
    IPIPItem(30, "Do not have a good imagination.", "openness", "-"),
    IPIPItem(31, "Talk to a lot of different people at parties.", "extraversion", "+"),
    IPIPItem(32, "Am not really interested in others.", "agreeableness", "-"),
    IPIPItem(33, "Like order.", "conscientiousness", "+"),
    IPIPItem(34, "Change my mood a lot.", "neuroticism", "+"),
    IPIPItem(35, "Am quick to understand things.", "openness", "+"),
    IPIPItem(36, "Don't like to draw attention to myself.", "extraversion", "-"),
    IPIPItem(37, "Take time out for others.", "agreeableness", "+"),
    IPIPItem(38, "Shirk my duties.", "conscientiousness", "-"),
    IPIPItem(39, "Have frequent mood swings.", "neuroticism", "+"),
    IPIPItem(40, "Use difficult words.", "openness", "+"),
    IPIPItem(41, "Don't mind being the center of attention.", "extraversion", "+"),
    IPIPItem(42, "Feel others' emotions.", "agreeableness", "+"),
    IPIPItem(43, "Follow a schedule.", "conscientiousness", "+"),
    IPIPItem(44, "Get irritated easily.", "neuroticism", "+"),
    IPIPItem(45, "Spend time reflecting on things.", "openness", "+"),
    IPIPItem(46, "Am quiet around strangers.", "extraversion", "-"),
    IPIPItem(47, "Make people feel at ease.", "agreeableness", "+"),
    IPIPItem(48, "Am exacting in my work.", "conscientiousness", "+"),
    IPIPItem(49, "Often feel blue.", "neuroticism", "+"),
    IPIPItem(50, "Am full of ideas.", "openness", "+"),
]

assert len(IPIP50) == 50
assert all(len([i for i in IPIP50 if i.trait == t]) == 10 for t in {i.trait for i in IPIP50})
