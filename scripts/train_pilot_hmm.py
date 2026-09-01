#!/usr/bin/env python3
"""Quality-gate labelled lab trials and fit the reported upper HMM."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.lhmm.upper import STATES  # noqa: E402
from hrc_safety.pilot_model import save_upper_hmm  # noqa: E402
from hrc_safety.pilot_training import (  # noqa: E402
    complete_trials,
    fit_trials,
    leave_one_trial_out,
    load_trials,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/xsens", help="recording directory")
    parser.add_argument(
        "--output", default="data/models/pilot_hmm.json", help="fitted model JSON"
    )
    parser.add_argument("--min-complete-trials", type=int, default=3)
    parser.add_argument("--min-samples-per-state", type=int, default=30)
    parser.add_argument(
        "--check-only", action="store_true", help="report readiness without fitting"
    )
    args = parser.parse_args()

    trials = load_trials(args.input)
    if not trials:
        print(f"No JSONL recordings found in {Path(args.input).resolve()}")
        return 2

    print("Pilot-data quality gate")
    print(f"  required states: {', '.join(STATES)}")
    print(f"  minimum labelled samples/state/trial: {args.min_samples_per_state}")
    print()
    for trial in trials:
        counts = trial.counts
        count_text = " ".join(f"{state[:4]}={counts[state]:5d}" for state in STATES)
        ready = "COMPLETE" if trial.is_complete(args.min_samples_per_state) else "incomplete"
        print(
            f"  {trial.trial_id:>6}  {ready:<10} {count_text} "
            f"skipped={trial.skipped_rows}"
        )

    usable = complete_trials(trials, args.min_samples_per_state)
    print()
    print(
        f"Complete loops: {len(usable)}/{args.min_complete_trials} required "
        f"({len(trials)} recordings scanned)"
    )
    if len(usable) < args.min_complete_trials:
        remaining = args.min_complete_trials - len(usable)
        print(
            f"NOT READY: collect at least {remaining} more complete loop(s), with every "
            "state labelled. No model was written."
        )
        return 2
    if args.check_only:
        print("READY: quality gate passed; run again without --check-only to fit.")
        return 0

    model = fit_trials(usable)
    validation = leave_one_trial_out(usable)
    summary = {
        "recordings_scanned": len(trials),
        "complete_trials": len(usable),
        "training_trial_ids": [trial.trial_id for trial in usable],
        "label_counts": {
            state: sum(trial.counts[state] for trial in usable) for state in STATES
        },
        "min_samples_per_state_per_trial": args.min_samples_per_state,
    }
    target = save_upper_hmm(
        args.output,
        model,
        source="labelled real pilot recordings",
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        data_summary=summary,
        validation=validation,
    )
    print(f"FITTED: {target.resolve()}")
    print(
        "LOTO validation: "
        f"accuracy={validation['accuracy']:.3f} "
        f"hazard_precision={validation['hazard_precision']:.3f} "
        f"hazard_recall={validation['hazard_recall']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
