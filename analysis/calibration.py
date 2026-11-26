"""Experiment 3 — calibration: does higher confidence mean lower error?

Bins every (inferred, ground-truth) trait estimate by the agent's reported confidence and reports
mean absolute error per bin. A well-calibrated profiler shows error falling as confidence rises.
"""

from __future__ import annotations

import csv

from analysis.common import (
    ALL_TRAITS,
    ensure_output,
    ground_truth,
    load_participants,
    load_sessions,
)

BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def main() -> None:
    sessions = load_sessions()
    participants = load_participants()
    buckets: dict[tuple[float, float], list[float]] = {b: [] for b in BINS}
    for s in sessions:
        truth = ground_truth(s, participants)
        if not truth or not s.inferred_profile:
            continue
        for t in ALL_TRAITS:
            if t not in truth or t not in s.inferred_profile:
                continue
            conf = float(s.inferred_confidence.get(t, 0.0))
            err = abs(float(s.inferred_profile[t]) - float(truth[t]))
            for lo, hi in BINS:
                if lo <= conf < hi:
                    buckets[(lo, hi)].append(err)
                    break

    out = ensure_output() / "calibration.csv"
    print("\nCalibration: mean error by confidence bin\n")
    print(f"{'confidence bin':<18}{'n':>5}{'mean error':>12}")
    rows = []
    for (lo, hi), errs in buckets.items():
        m = round(sum(errs) / len(errs), 3) if errs else None
        label = f"{lo:.1f}-{hi if hi <= 1 else 1.0:.1f}"
        print(f"{label:<18}{len(errs):>5}{('n/a' if m is None else f'{m:.3f}'):>12}")
        rows.append({"bin": label, "n": len(errs), "mean_error": m})
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["bin", "n", "mean_error"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
