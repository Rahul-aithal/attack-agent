"""Experiment 4 — twin prediction: match rate and a confusion matrix of twin-predicted vs real
outcome, broken down by selection mode."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict

from analysis.common import ensure_output, load_sessions

OUTCOMES = ["SUCCESS", "PARTIAL", "FAILURE", "INCOMPLETE"]


def main() -> None:
    sessions = [s for s in load_sessions() if s.twin_outcome and s.real_outcome]
    if not sessions:
        print("no sessions with both twin and real outcomes yet.")
        return

    by_mode: dict[str, list] = defaultdict(list)
    for s in sessions:
        by_mode[s.selection_mode or "unknown"].append(s)

    print(f"\nTwin prediction match over {len(sessions)} sessions\n")
    print(f"{'selection mode':<20}{'n':>5}{'match rate':>12}")
    for mode, rows in by_mode.items():
        matches = sum(1 for s in rows if s.match_flag)
        print(f"{mode:<20}{len(rows):>5}{matches / len(rows):>12.2%}")

    confusion: Counter = Counter()
    for s in sessions:
        confusion[(s.twin_outcome, s.real_outcome)] += 1

    print("\nConfusion matrix (rows = twin predicted, cols = real):\n")
    header = "pred\\real".ljust(12) + "".join(o[:7].rjust(10) for o in OUTCOMES)
    print(header)
    out = ensure_output() / "twin_confusion.csv"
    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["twin_pred\\real", *OUTCOMES])
        for pred in OUTCOMES:
            cells = [confusion.get((pred, real), 0) for real in OUTCOMES]
            print(pred.ljust(12) + "".join(str(c).rjust(10) for c in cells))
            writer.writerow([pred, *cells])
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
