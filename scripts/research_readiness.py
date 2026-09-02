#!/usr/bin/env python3
"""Fail closed when collection or reporting evidence is incomplete."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def audit(root: Path, stage: str = "collection") -> list[tuple[str, str]]:
    manifest_path = root / "configs" / "research_readiness.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    failures: list[tuple[str, str]] = []

    for gate_id, gate in manifest.get("gates", {}).items():
        if stage == "collection" and gate.get("stage") == "report":
            continue
        evidence = gate.get("evidence")
        complete = gate.get("complete") is True
        evidence_exists = bool(evidence) and (root / str(evidence)).is_file()
        if not complete or not evidence_exists:
            failures.append((gate_id, str(gate.get("requirement", "missing evidence"))))

    model_path = root / "data" / "models" / "pilot_hmm.json"
    if not model_path.exists():
        failures.append(("model_exists", "No fitted pilot model artifact exists."))

    if stage == "report":
        metrics_path = root / "data" / "analysis" / "metrics.json"
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            if "synthetic" in str(metrics.get("source", "")).lower():
                failures.append((
                    "reported_results_are_real",
                    "Current controller-comparison metrics are synthetic and cannot be reported.",
                ))
        else:
            failures.append((
                "reported_results_exist",
                "No controller-comparison metrics artifact exists."))

        if model_path.exists():
            model = json.loads(model_path.read_text(encoding="utf-8"))
            role = str(model.get("validation", {}).get("role", ""))
            if "development estimate" in role.lower():
                failures.append((
                    "model_has_final_test",
                    "The active model is explicitly marked as development-only, not final test evidence.",
                ))

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage", choices=("collection", "report"), default="collection")
    args = parser.parse_args()
    failures = audit(args.root.resolve(), stage=args.stage)
    if failures:
        target = ("participant data collection" if args.stage == "collection"
                  else "reported study claims")
        print(f"NOT READY for {target}")
        for gate_id, reason in failures:
            print(f"  BLOCKED {gate_id}: {reason}")
        return 2
    print(f"READY for {args.stage}: every applicable evidence gate has a committed witness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
