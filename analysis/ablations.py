"""Experiment 2 — ablations: compare profiling accuracy across configuration variants recorded in
each session's config_snapshot (profiler version, extractor mode, stopping rule, selection mode).

Group sessions by a chosen config key and report overall MAE and twin match rate per group, so
runs produced with different `attack-agent-eval` flags can be compared side by side.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from analysis.common import (
    ALL_TRAITS,
    ground_truth,
    load_participants,
    load_sessions,
    mae,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--key",
        default="profiler_version",
        help="config_snapshot key to group by (e.g. profiler_version, extractor_mode, "
        "stopping_rule, selection_mode)",
    )
    args = parser.parse_args()

    sessions = load_sessions()
    participants = load_participants()
    groups: dict[str, list] = defaultdict(list)
    for s in sessions:
        value = (s.config_snapshot or {}).get(args.key, "unset")
        groups[str(value)].append(s)

    print(f"\nAblation by '{args.key}'\n")
    print(f"{args.key:<22}{'n':>5}{'MAE':>8}{'match rate':>12}")
    for value, rows in sorted(groups.items()):
        inf: list[float] = []
        tru: list[float] = []
        matched = total_outcome = 0
        for s in rows:
            truth = ground_truth(s, participants)
            if truth and s.inferred_profile:
                for t in ALL_TRAITS:
                    if t in truth and t in s.inferred_profile:
                        inf.append(float(s.inferred_profile[t]))
                        tru.append(float(truth[t]))
            if s.real_outcome and s.twin_outcome:
                total_outcome += 1
                matched += 1 if s.match_flag else 0
        m = mae(inf, tru)
        rate = f"{matched / total_outcome:.0%}" if total_outcome else "n/a"
        print(f"{value:<22}{len(rows):>5}{('n/a' if m is None else f'{m:.3f}'):>8}{rate:>12}")
    print()


if __name__ == "__main__":
    main()
