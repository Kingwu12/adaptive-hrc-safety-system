#!/usr/bin/env python3
"""End-to-end simulation: fit models, run both controllers, print the comparison.

Workflow (the EXACT workflow pilot data will follow):
  1. load config; print zone geometry.
  2. generate a held-out TEST trace.
  3. FIT emissions + transition matrix A from 3 separately-seeded labelled TRAINING
     traces -- never from the test trace, never from hand-set numbers.
  4. run BOTH controllers over the identical test trace, writing JSONL decision logs.
  5. print the fitted A, the LHMM recognition report, and a side-by-side metric table.

Reported pilot results replace the synthetic ones; synthetic data never appears in
the paper (see docs/experiment_plan.md).
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.config import build_zone_model, load_config  # noqa: E402
from hrc_safety.controllers import AdaptiveController, StaticController  # noqa: E402
from hrc_safety.lhmm.upper import STATES, UpperHMM  # noqa: E402
from hrc_safety.logging_schema import JsonlLogger  # noqa: E402
from hrc_safety.metrics import compute_metrics, recognition_report  # noqa: E402
from hrc_safety.sim.runner import (  # noqa: E402
    extract_frames,
    observation_matrix,
    run_controller,
)
from hrc_safety.sim.scenario import generate_loop  # noqa: E402

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "logs")


def _fit_models(config: dict) -> UpperHMM:
    """Fit A and emissions from 3 separately-seeded labelled training loops."""
    obs_chunks: list[np.ndarray] = []
    all_labels: list[str] = []
    label_sequences: list[list[str]] = []
    for seed in (101, 202, 303):
        trace = generate_loop(config, seed=seed)
        frames, labels = extract_frames(config, trace)
        obs = observation_matrix(frames)
        obs_chunks.append(obs)
        all_labels.extend(labels)
        label_sequences.append(labels)

    X = np.concatenate(obs_chunks, axis=0)
    A = UpperHMM.fit_transitions(label_sequences, laplace=1.0)
    emissions = UpperHMM.fit_emissions(X, all_labels, var_floor=1e-3)
    return UpperHMM(transition_matrix=A, emissions=emissions)


def _print_matrix(A: np.ndarray) -> None:
    header = "            " + "".join(f"{s[:5]:>8}" for s in STATES)
    print(header)
    for i, s in enumerate(STATES):
        row = "".join(f"{A[i, j]:8.3f}" for j in range(len(STATES)))
        print(f"  {s:>9} {row}")


def main() -> None:
    config = load_config()
    zones = build_zone_model(config)

    print("=" * 68)
    print("Adaptive vs Static HRC Safety -- Simulation")
    print("=" * 68)
    print("\nZone geometry (ISO/TS 15066  S0 = K*T + C + Sa):")
    print(f"  S0 (red radius)   = {zones.S0:.3f} m")
    print(f"  yellow radius     = {zones.yellow_radius:.3f} m")
    print(f"  work_radius       = {config['scenario']['work_radius']:.3f} m "
          "(inside yellow, outside red)")

    # Held-out test trace.
    test_trace = generate_loop(config, seed=7)

    # Fit the REPORTED model from separate training traces.
    fitted = _fit_models(config)
    print("\nFitted transition matrix A (from labelled training loops):")
    _print_matrix(fitted.A)

    # Recognition validation (offline Viterbi vs ground truth) on the test trace.
    frames, test_labels = extract_frames(config, test_trace)
    predicted_path = fitted.viterbi(observation_matrix(frames))
    rep = recognition_report(predicted_path, test_labels)
    print("\nLHMM recognition report (test trace, Viterbi vs ground truth):")
    print(f"  accuracy          = {rep.accuracy:.3f}")
    print(f"  hazard precision  = {rep.hazard_precision:.3f}")
    print(f"  hazard recall     = {rep.hazard_recall:.3f}")
    print("  confusion (rows=true, cols=pred):")
    _print_matrix(rep.confusion.astype(float))

    # Run BOTH controllers over the identical test trace.
    os.makedirs(LOG_DIR, exist_ok=True)
    dt = test_trace.dt

    static = StaticController(
        build_zone_model(config),
        speed_reduced=config["controller"]["speed_reduced"],
    )
    fitted.reset()
    adaptive = AdaptiveController(
        build_zone_model(config),
        fitted,
        speed_reduced=config["controller"]["speed_reduced"],
        hazard_prob_threshold=config["lhmm"]["hazard_prob_threshold"],
        hazard_dwell_ticks=config["lhmm"]["hazard_dwell_ticks"],
        working_stability_ticks=config["controller"]["working_stability_ticks"],
    )

    results = {}
    for name, controller in (("static", static), ("adaptive", adaptive)):
        run = run_controller(config, controller, test_trace)
        logger = JsonlLogger(os.path.join(LOG_DIR, f"{name}.jsonl"))
        for rec in run.records:
            logger.log(rec)
        logger.flush()
        metrics = compute_metrics(
            run.records, run.labels, dt, test_trace.hazard_onset_t
        )
        results[name] = metrics

    # Side-by-side metric table.
    print("\nMetric comparison (identical test trace):")
    print(f"  {'metric':<32}{'static':>12}{'adaptive':>12}")
    print("  " + "-" * 56)

    def row(label: str, key, fmt="{:.3f}"):
        s = getattr(results["static"], key)
        a = getattr(results["adaptive"], key)
        sv = "n/a" if s is None else fmt.format(s)
        av = "n/a" if a is None else fmt.format(a)
        print(f"  {label:<32}{sv:>12}{av:>12}")

    row("min separation (m)", "min_separation")
    row("stop episodes", "stop_episodes", "{:d}")
    row("stop duration (s)", "stop_duration_s")
    row("slowdown episodes", "slowdown_episodes", "{:d}")
    row("slowdown duration (s)", "slowdown_duration_s")
    row("unnecessary interruption (s)", "unnecessary_interruption_s")
    row("hazard response latency (s)", "hazard_response_latency_s")

    print(f"\nDecision logs written to {os.path.normpath(LOG_DIR)}/")


if __name__ == "__main__":
    main()
