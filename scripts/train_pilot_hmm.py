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
    leave_one_participant_out,
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
        "--emission-components",
        type=int,
        default=2,
        help="diagonal Gaussian components per state (default: 2)",
    )
    parser.add_argument(
        "--participants",
        help="comma-separated participant IDs to include (for example P03,P04,P05)",
    )
    parser.add_argument(
        "--validation",
        choices=("auto", "participant", "trial"),
        default="auto",
        help="validation split; auto uses participant-level when possible",
    )
    parser.add_argument(
        "--check-only", action="store_true", help="report readiness without fitting"
    )
    args = parser.parse_args()
    if args.emission_components < 1:
        parser.error("--emission-components must be at least one")

    scanned = load_trials(args.input)
    if not scanned:
        print(f"No JSONL recordings found in {Path(args.input).resolve()}")
        return 2
    selected_ids = None
    if args.participants:
        selected_ids = {value.strip() for value in args.participants.split(",")
                        if value.strip()}
        if not selected_ids:
            print("No valid participant IDs were supplied")
            return 2
    trials = [trial for trial in scanned
              if selected_ids is None or trial.participant_id in selected_ids]
    if not trials:
        print("No recordings matched the participant filter")
        return 2

    print("Pilot-data quality gate")
    print(f"  required states: {', '.join(STATES)}")
    print(f"  minimum labelled samples/state/trial: {args.min_samples_per_state}")
    if selected_ids is not None:
        print(f"  participant filter: {', '.join(sorted(selected_ids))}")
    print()
    for trial in trials:
        counts = trial.counts
        count_text = " ".join(f"{state[:4]}={counts[state]:5d}" for state in STATES)
        ready = "COMPLETE" if trial.is_complete(args.min_samples_per_state) else "incomplete"
        print(
            f"  {trial.participant_id:>5}/{trial.trial_id:<5} {ready:<10} {count_text} "
            f"skipped={trial.skipped_rows}"
        )

    usable = complete_trials(trials, args.min_samples_per_state)
    print()
    print(
        f"Complete loops: {len(usable)}/{args.min_complete_trials} required "
        f"({len(trials)} selected; {len(scanned)} recordings scanned)"
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

    participant_ids = sorted({trial.participant_id for trial in usable})
    validation_method = args.validation
    if validation_method == "auto":
        validation_method = "participant" if len(participant_ids) >= 2 else "trial"
    if validation_method == "participant" and len(participant_ids) < 2:
        print("NOT READY: participant-level validation requires at least two participants")
        return 2

    model = fit_trials(usable, args.emission_components)
    validation = (leave_one_participant_out(usable, args.emission_components)
                  if validation_method == "participant"
                  else leave_one_trial_out(usable, args.emission_components))
    validation["role"] = (
        "development estimate; if this configuration was selected using these "
        "folds, confirm it once on a newly recruited untouched participant"
    )
    summary = {
        "recordings_scanned": len(scanned),
        "recordings_selected": len(trials),
        "complete_trials": len(usable),
        "participants": participant_ids,
        "training_runs": [
            {"participant_id": trial.participant_id,
             "trial_id": trial.trial_id,
             "file_name": trial.path.name}
            for trial in usable
        ],
        "label_counts": {
            state: sum(trial.counts[state] for trial in usable) for state in STATES
        },
        "min_samples_per_state_per_trial": args.min_samples_per_state,
        "feature_order": ["d", "v_proj", "speed", "a_proj"],
        "emission_components_per_state": args.emission_components,
    }
    target = save_upper_hmm(
        args.output,
        model,
        source=("labelled real pilot recordings · "
                f"{args.emission_components}-component diagonal GMM"),
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        data_summary=summary,
        validation=validation,
    )
    print(f"FITTED: {target.resolve()}")
    print(
        f"Observation: d, v_proj, speed, a_proj; "
        f"emission components/state: {args.emission_components}"
    )
    print(
        f"{validation['method']} validation: "
        f"accuracy={validation['accuracy']:.3f} "
        f"hazard_precision={validation['hazard_precision']:.3f} "
        f"hazard_recall={validation['hazard_recall']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
