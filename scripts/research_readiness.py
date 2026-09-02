#!/usr/bin/env python3
"""Fail closed when evidence for a reported moving-participant run is incomplete."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def audit(root: Path) -> list[tuple[str, str]]:
    manifest_path = root / "configs" / "research_readiness.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    failures: list[tuple[str, str]] = []

    for gate_id, gate in manifest.get("gates", {}).items():
        evidence = gate.get("evidence")
        complete = gate.get("complete") is True
        evidence_exists = bool(evidence) and (root / str(evidence)).is_file()
        if not complete or not evidence_exists:
            failures.append((gate_id, str(gate.get("requirement", "missing evidence"))))

    metrics_path = root / "data" / "analysis" / "metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        if "synthetic" in str(metrics.get("source", "")).lower():
            failures.append((
                "reported_results_are_real",
                "Current controller-comparison metrics are synthetic and cannot be reported.",
            ))
    else:
        failures.append(("reported_results_exist", "No controller-comparison metrics artifact exists."))

    model_path = root / "data" / "models" / "pilot_hmm.json"
    if model_path.exists():
        model = json.loads(model_path.read_text(encoding="utf-8"))
        role = str(model.get("validation", {}).get("role", ""))
        if "development estimate" in role.lower():
            failures.append((
                "model_has_final_test",
                "The active model is explicitly marked as development-only, not final test evidence.",
            ))
    else:
        failures.append(("model_exists", "No fitted pilot model artifact exists."))

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    failures = audit(args.root.resolve())
    if failures:
        print("NOT READY for a reported moving-participant controller run")
        for gate_id, reason in failures:
            print(f"  BLOCKED {gate_id}: {reason}")
        return 2
    print("READY: every declared evidence gate has a committed witness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
