#!/usr/bin/env python3
"""Freeze the qualified model, controller and analysis inputs before participants."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


FROZEN_PATHS = (
    "data/models/pilot_hmm.json",
    "configs/default.yaml",
    "docs/experiment_plan.md",
    "src/hrc_safety/features.py",
    "src/hrc_safety/horizon.py",
    "src/hrc_safety/controllers/controllers.py",
    "src/hrc_safety/lhmm/upper.py",
    "src/hrc_safety/pilot_model.py",
    "src/hrc_safety/metrics.py",
    "scripts/dashboard_server.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_freeze(root: Path, qualification_report: Path) -> dict:
    report = json.loads(qualification_report.read_text(encoding="utf-8"))
    captures = report.get("captures", [])
    if report.get("result") != "pass" or report.get("trial_batch") is not True:
        raise ValueError("qualification report is not a passing trial batch")
    if len(captures) < 10:
        raise ValueError("qualification report contains fewer than 10 captures")

    model = json.loads((root / "data/models/pilot_hmm.json").read_text(encoding="utf-8"))
    validation = model.get("validation", {})
    if model.get("schema_version") != 3:
        raise ValueError("active model is not schema version 3")
    if model.get("states") != ["approaching", "working", "retreating"]:
        raise ValueError("active model is not the frozen three-phase definition")
    if float(validation.get("accuracy", 0.0)) < 0.80:
        raise ValueError("participant-held-out development accuracy is below 0.80")

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    if dirty:
        raise ValueError("tracked files are dirty; commit and verify before freezing")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True,
        capture_output=True, check=True).stdout.strip()

    missing = [relative for relative in FROZEN_PATHS if not (root / relative).is_file()]
    if missing:
        raise ValueError("missing frozen inputs: " + ", ".join(missing))
    qualification_models = {
        item.get("model_sha256") for item in captures if item.get("model_sha256")}
    active_model_hash = sha256(root / "data/models/pilot_hmm.json")
    if qualification_models != {active_model_hash}:
        raise ValueError("qualification runs were not recorded with the active model")

    return {
        "schema_version": 1,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "qualification_report": str(qualification_report.resolve()),
        "qualification_report_sha256": sha256(qualification_report),
        "qualification_capture_count": len(captures),
        "model_validation": {
            "method": validation.get("method"),
            "accuracy": validation.get("accuracy"),
            "balanced_accuracy": validation.get("balanced_accuracy"),
            "online_filter_accuracy": validation.get("online_filter_accuracy"),
        },
        "files": {
            relative: sha256(root / relative) for relative in FROZEN_PATHS
        },
        "rule": (
            "Do not retrain, retune, or change hashed inputs after the first "
            "reported participant. Any required change creates a new study release."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qualification_report", type=Path)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/verification/study-release.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        payload = build_freeze(root, args.qualification_report.resolve())
    except (OSError, ValueError, json.JSONDecodeError,
            subprocess.CalledProcessError) as exc:
        print(f"STUDY FREEZE BLOCKED: {exc}")
        return 2
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"STUDY RELEASE FROZEN: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
