#!/usr/bin/env python3
"""End-to-end simulation: fit models, run the THREE-RUNG ladder, print comparisons.

Workflow (the EXACT workflow pilot data will follow):
  1. load config; print zone + envelope geometry.
  2. generate a held-out TEST trace (with cued distractors + the slip).
  3. FIT emissions + transition matrix A from separately-seeded labelled TRAINING
     traces -- never from the test trace, never from hand-set numbers.
  4. run the THREE rungs over the identical test trace, writing JSONL decision logs:
       fixed_zone   -- deployed practice (fixed distance threshold)
       dynamic_ssm  -- ISO/TS 15066 speed-aware envelope alone (the standards rung)
       adaptive     -- full system (envelope floor + LHMM state + horizon prediction)
  5. print the fitted A, the LHMM recognition report, a 3-column metric table, and an
     ABLATION table (full system minus prediction; full minus the state layer), and
     write a machine-readable metrics JSON that the paper-table generator consumes.

Reported pilot results replace the synthetic ones; synthetic data never appears in
the paper (see docs/experiment_plan.md).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.analysis import (  # noqa: E402
    ABLATIONS,
    RUNGS,
    TEST_SEED,
    build_controller,
    fit_hmm,
    metrics_to_dict,
    phase_metrics_from_run,
    phase_metrics_to_dict,
    score_run,
)
from hrc_safety.config import build_zone_model, load_config  # noqa: E402
from hrc_safety.envelope import build_envelope  # noqa: E402
from hrc_safety.lhmm.upper import STATES  # noqa: E402
from hrc_safety.logging_schema import JsonlLogger  # noqa: E402
from hrc_safety.metrics import recognition_report  # noqa: E402
from hrc_safety.panel_cycle import PHASES  # noqa: E402
from hrc_safety.sim.runner import extract_frames, observation_matrix, run_controller  # noqa: E402
from hrc_safety.sim.scenario import generate_loop  # noqa: E402

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "logs")
ANALYSIS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "analysis")


def _print_matrix(A) -> None:
    header = "            " + "".join(f"{s[:5]:>8}" for s in STATES)
    print(header)
    for i, s in enumerate(STATES):
        row = "".join(f"{A[i, j]:8.3f}" for j in range(len(STATES)))
        print(f"  {s:>9} {row}")


def _run_and_log(config, name, controller, trace):
    """Run a controller ONCE, write its JSONL log, and derive flat + per-phase metrics.

    Running once matters: controllers are stateful (LHMM belief + risk streaks), so the
    logged records and the scored metrics MUST come from the same pass -- re-running the
    same instance would carry state across the boundary and desync the two.
    """
    run = run_controller(config, controller, trace)
    logger = JsonlLogger(os.path.join(LOG_DIR, f"{name}.jsonl"))
    for rec in run.records:
        logger.log(rec)
    logger.flush()
    flat = score_run(config, run, trace)
    phase = phase_metrics_from_run(run, trace)
    return flat, phase


def _print_table(columns, results) -> None:
    """Print a metric table with one column per named controller."""
    width = 14
    head = f"  {'metric':<30}" + "".join(f"{c[:width - 1]:>{width}}" for c in columns)
    print(head)
    print("  " + "-" * (30 + width * len(columns)))

    def row(label, key, fmt="{:.3f}"):
        cells = ""
        for c in columns:
            v = results[c].get(key)
            cells += f"{('n/a' if v is None else fmt.format(v)):>{width}}"
        print(f"  {label:<30}{cells}")

    print("  [PRIMARY]")
    row("interruption burden (s)", "interruption_burden_s")
    print("  [safety]")
    row("min separation (m)", "min_separation")
    row("hazard sensitivity", "hazard_sensitivity")
    row("hazard specificity", "hazard_specificity")
    row("false stop rate", "false_stop_rate")
    row("anticipation lead time (s)", "anticipation_lead_time_s")
    print("  [secondary / sem-1 continuity]")
    row("stop episodes", "stop_episodes", "{:d}")
    row("slowdown episodes", "slowdown_episodes", "{:d}")
    row("unnecessary interruption (s)", "unnecessary_interruption_s")
    row("hazard response latency (s)", "hazard_response_latency_s")


def _print_phase_table(columns, phase_metrics) -> None:
    """Print, per phase, the key per-condition numbers with one column per controller."""
    width = 14
    for phase in PHASES:
        # Header line with the phase and its measurement-window / mode annotation.
        sample = next((phase_metrics[c].get(phase) for c in columns if phase_metrics[c].get(phase)), None)
        if sample is None:
            continue
        tag = "MEASURE" if sample["is_measurement_window"] else "not measured"
        print(f"\n  [{phase}]  mode={sample['collaborative_mode']}  ({tag})")
        head = f"    {'metric':<26}" + "".join(f"{c[:width - 1]:>{width}}" for c in columns)
        print(head)

        def row(label, key, fmt="{:.3f}"):
            cells = ""
            for c in columns:
                pm = phase_metrics[c].get(phase)
                v = None if pm is None else pm.get(key)
                cells += f"{('n/a' if v is None else fmt.format(v)):>{width}}"
            print(f"    {label:<26}{cells}")

        row("duration / cycle time (s)", "duration_s")
        row("min separation (m)", "min_separation")
        row("protective-stop count", "stop_episodes", "{:d}")
        row("stop duration (s)", "stop_duration_s")
        row("human idle (s)", "human_idle_s")
        row("speed deficit (s)", "speed_deficit_s")


def main() -> None:
    config = load_config()
    zones = build_zone_model(config)
    envelope = build_envelope(config)
    K = config["zones"]["K"]

    print("=" * 74)
    print("Adaptive vs Static HRC Safety -- Three-Rung Simulation")
    print("=" * 74)
    print("\nZone geometry (fixed ISO/TS 15066  S0 = K*T + C + Sa):")
    print(f"  fixed RED radius  = {zones.S0:.3f} m   (K={K} worst case)")
    print(f"  yellow radius     = {zones.yellow_radius:.3f} m")
    print("\nDynamic SSM envelope stop distance  S(t) = max(0,v_proj)*T + C + Sa:")
    print(f"  at v_proj=0.0     = {envelope.stop_distance(0.0):.3f} m  (stationary worker)")
    print(f"  at v_proj={K:.1f}     = {envelope.stop_distance(K):.3f} m"
          "  (== fixed RED radius, by construction)")
    print(f"  ramp band         = {config['envelope']['ramp']:.3f} m (speed scales 0->1 across it)")

    # Held-out test trace (carries the cued distractors + the slip).
    test_trace = generate_loop(config, seed=TEST_SEED)

    # Fit the REPORTED model from separate training traces.
    fitted = fit_hmm(config)
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

    os.makedirs(LOG_DIR, exist_ok=True)

    # --- THREE-RUNG comparison + the two ablations (dedupe: 'adaptive' shared) -
    all_names = list(dict.fromkeys(RUNGS + ABLATIONS))  # preserve order, no repeats
    metrics = {}
    phase_metrics = {}
    for name in all_names:
        controller = build_controller(name, config, fitted)
        flat, phase = _run_and_log(config, name, controller, test_trace)
        metrics[name] = metrics_to_dict(flat)
        phase_metrics[name] = phase_metrics_to_dict(phase)

    print("\nThree-rung metric comparison (identical test trace):")
    _print_table(list(RUNGS), metrics)

    print("\nAblation (full system minus one ingredient):")
    _print_table(list(ABLATIONS), metrics)

    print("\nPer-phase measurement-window comparison (P4 HOLD_BOLT is NOT measured):")
    _print_phase_table(list(RUNGS), phase_metrics)

    # --- machine-readable metrics for the paper pipeline ----------------------
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    out = {
        "source": "SYNTHETIC (pipeline validation only -- NOT reported; see docs/experiment_plan.md)",
        "test_seed": TEST_SEED,
        "geometry": {
            "fixed_red_radius_m": zones.S0,
            "yellow_radius_m": zones.yellow_radius,
            "envelope_stop_at_v0_m": envelope.stop_distance(0.0),
        },
        "recognition": {
            "accuracy": rep.accuracy,
            "hazard_precision": rep.hazard_precision,
            "hazard_recall": rep.hazard_recall,
        },
        "metrics": metrics,
        "phase_metrics": phase_metrics,
    }
    metrics_path = os.path.join(ANALYSIS_DIR, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    print(f"\nDecision logs written to {os.path.normpath(LOG_DIR)}/")
    print(f"Metrics JSON written to  {os.path.normpath(metrics_path)}")


if __name__ == "__main__":
    main()
