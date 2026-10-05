#!/usr/bin/env python3
"""Per-phase recall of the reported pilot HMM for both decoders.

The stored model (data/models/pilot_hmm.json) keeps per-phase recall only for
offline Viterbi decoding. This reruns the same leave-one-operator-out validation
on the same 32 recordings and settings, refuses to write anything unless every
stored value is reproduced, and saves the causal-filter recalls alongside.
The model file itself is not modified.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hrc_safety.features import LEGACY_FEATURE_ORDER  # noqa: E402
from hrc_safety.pilot_training import leave_one_participant_out, load_trial  # noqa: E402

MODEL = ROOT / "data" / "models" / "pilot_hmm.json"
OUT = ROOT / "data" / "models" / "pilot_hmm_phase_recall.json"


def main() -> int:
    model = json.loads(MODEL.read_text(encoding="utf8"))
    summary, stored = model["data_summary"], model["validation"]
    trials = [load_trial(ROOT / "data" / "xsens" / run["file_name"], LEGACY_FEATURE_ORDER)
              for run in summary["training_runs"]]
    rerun = leave_one_participant_out(trials, summary["emission_components_per_state"],
                                      summary["transition_power"])
    checks = {key: (stored[key], rerun[key]) for key in (
        "accuracy", "balanced_accuracy", "online_filter_accuracy", "online_filter_balanced_accuracy")}
    checks.update({f"viterbi_recall_{k}": (v, rerun["per_phase_recall"][k])
                   for k, v in stored["per_phase_recall"].items()})
    failed = {k: v for k, v in checks.items() if not math.isclose(*v, abs_tol=1e-9)}
    if failed:
        print(f"Rerun does not reproduce the stored validation; nothing written: {failed}")
        return 1
    result = {
        "source_model": os.path.relpath(MODEL, ROOT),
        "method": rerun["method"],
        "participants": rerun["participants"],
        "reproduced_stored_values": sorted(checks),
        "viterbi_per_phase_recall": rerun["per_phase_recall"],
        "causal_per_phase_recall": rerun["online_filter_per_phase_recall"],
        "causal_confusion": rerun["online_filter_confusion"],
        "folds": [{"participant_id": f["participant_id"],
                   "viterbi_per_phase_recall": f["per_phase_recall"],
                   "causal_per_phase_recall": f["online_filter_per_phase_recall"]}
                  for f in rerun["folds"]],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"viterbi": result["viterbi_per_phase_recall"],
                      "causal": result["causal_per_phase_recall"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
