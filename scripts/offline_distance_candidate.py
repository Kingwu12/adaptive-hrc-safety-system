#!/usr/bin/env python3
"""Compare distinct fixed and adaptive distances offline; never command the rig."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import yaml


FIELDS = (
    "static_stop_m", "static_warning_m", "adaptive_min_m",
    "end_to_end_stop_time_s", "sensing_uncertainty_m",
    "protected_geometry_margin_m", "adaptive_speed_ramp_m",
)
EVIDENCE = ("stop_time", "sensing_uncertainty", "protected_geometry", "safety_rated_output")


def load_candidate(path: Path) -> dict[str, float]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Distance worksheet must be a YAML mapping")
    if raw.get("status") != "development_only":
        raise ValueError("Distance worksheet must remain development_only")
    missing = [name for name in FIELDS if raw.get(name) is None]
    if missing:
        raise ValueError("Measured candidate inputs missing: " + ", ".join(missing))
    values = {name: float(raw[name]) for name in FIELDS}
    if not all(math.isfinite(v) and v > 0 for v in values.values()):
        raise ValueError("All measured candidate inputs must be finite and positive")
    if not values["adaptive_min_m"] < values["static_stop_m"] < values["static_warning_m"]:
        raise ValueError("Require adaptive minimum < fixed stop < fixed warning")
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict) or any(
        not isinstance(evidence.get(name), str) or not evidence[name].strip()
        for name in EVIDENCE
    ):
        raise ValueError("Document stop time, sensing, geometry and safeguard evidence")
    return values


def compare(values: dict[str, float], distance_m: float,
            closing_m_s: float, phase_cap: float = 1.0) -> dict[str, float]:
    if not all(math.isfinite(v) for v in (distance_m, closing_m_s, phase_cap)):
        raise ValueError("Scenario inputs must be finite")
    if not 0 <= phase_cap <= 1 or distance_m < 0:
        raise ValueError("Invalid phase cap or distance")
    fixed = (0.0 if distance_m <= values["static_stop_m"] else
             .35 if distance_m <= values["static_warning_m"] else 1.0)
    measured_stop = (max(0.0, closing_m_s) * values["end_to_end_stop_time_s"]
                     + values["sensing_uncertainty_m"]
                     + values["protected_geometry_margin_m"])
    adaptive_stop = max(values["adaptive_min_m"], measured_stop)
    ramp = values["adaptive_speed_ramp_m"]
    reactive = min(1.0, max(0.0, (distance_m - adaptive_stop) / ramp))
    predictive = min(reactive, phase_cap)
    return {"fixed": fixed, "reactive": reactive, "predictive": predictive,
            "adaptive_stop_m": adaptive_stop}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=Path("configs/distance_candidate.yaml"))
    parser.add_argument("--distance-m", type=float, required=True)
    parser.add_argument("--closing-m-s", type=float, required=True)
    args = parser.parse_args()
    try:
        values = load_candidate(args.candidate)
    except ValueError as exc:
        parser.error(str(exc))
    print(compare(values, args.distance_m, args.closing_m_s))
    print("OFFLINE DEVELOPMENT ONLY: no robot commands or study release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
