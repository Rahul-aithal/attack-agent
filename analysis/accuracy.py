"""Experiment 1 — profiling accuracy: Pearson r and MAE per trait, inferred vs ground truth.

Ground truth is the persona's known traits (synthetic runs) or the self-report questionnaire.
Prints a per-trait table and writes outputs/analysis/accuracy.csv.
"""

from __future__ import annotations

import csv

from analysis.common import (
    ALL_TRAITS,
    ensure_output,
    ground_truth,
    load_participants,
    load_sessions,
    mae,
    pearson,
)


def main() -> None:
    sessions = load_sessions()
    participants = load_participants()
    pairs: dict[str, tuple[list[float], list[float]]] = {t: ([], []) for t in ALL_TRAITS}
    n_used = 0
    for s in sessions:
        truth = ground_truth(s, participants)
        if not truth or not s.inferred_profile:
            continue
        n_used += 1
        for t in ALL_TRAITS:
            if t in truth and t in s.inferred_profile:
                pairs[t][0].append(float(s.inferred_profile[t]))
                pairs[t][1].append(float(truth[t]))

    out = ensure_output() / "accuracy.csv"
    rows = []
    print(f"\nProfiling accuracy over {n_used} sessions (inferred vs ground truth)\n")
    print(f"{'trait':<18}{'n':>4}{'r':>8}{'MAE':>8}")
    all_inf: list[float] = []
    all_true: list[float] = []
    for t in ALL_TRAITS:
        inf, tru = pairs[t]
        r, m = pearson(inf, tru), mae(inf, tru)
        all_inf += inf
        all_true += tru
        print(f"{t:<18}{len(inf):>4}{_fmt(r):>8}{_fmt(m):>8}")
        rows.append({"trait": t, "n": len(inf), "pearson_r": r, "mae": m})
    overall_r, overall_mae = pearson(all_inf, all_true), mae(all_inf, all_true)
    print(f"{'OVERALL':<18}{len(all_inf):>4}{_fmt(overall_r):>8}{_fmt(overall_mae):>8}\n")
    rows.append({"trait": "overall", "n": len(all_inf), "pearson_r": overall_r, "mae": overall_mae})

    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["trait", "n", "pearson_r", "mae"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out}")


def _fmt(v) -> str:
    return "n/a" if v is None else f"{v:.3f}"


if __name__ == "__main__":
    main()
