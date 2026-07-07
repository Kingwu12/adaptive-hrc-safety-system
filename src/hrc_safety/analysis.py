"""Analysis harness -- the ONE place that builds a named controller and scores it.

SSOT rationale: three entry points need "given a config + a fitted model + a trace,
run controller X and produce metrics" -- the end-to-end script, the offline replay
tool, and the paper-table generator. If each built controllers its own way they would
drift (different thresholds, different envelope, different scoring args). This module
owns that construction and scoring so every surface reports the identical numbers.

A controller is addressed by a stable NAME (the rung / ablation id). The same names are
used as JSONL log stems, metrics-JSON keys, and LaTeX table columns, so a number can be
traced from the paper back to the exact controller that produced it.
"""

from __future__ import annotations

from dataclasses import asdict

import numpy as np

from .config import build_zone_model
from .controllers import (
    DynamicSSMController,
    EnvelopeAdaptiveController,
    FixedZoneController,
)
from .envelope import build_envelope
from .lhmm.upper import UpperHMM
from .metrics import (
    Metrics,
    PhaseMetrics,
    compute_metrics,
    compute_phase_metrics,
)
from .sim.runner import RunResult, extract_frames, observation_matrix, run_controller
from .sim.scenario import LoopTrace, generate_loop

# The three reported rungs, plus the two ablations. Order is display order.
RUNGS = ("fixed_zone", "dynamic_ssm", "adaptive")
ABLATIONS = ("adaptive", "adaptive_no_pred", "adaptive_no_state")

# Training seeds for the fitted model (never the test seed). Kept here so the script,
# the replay tool, and the tests all fit from the SAME loops.
TRAIN_SEEDS = (101, 202, 303)
TEST_SEED = 7


def fit_hmm(config: dict, seeds: tuple[int, ...] = TRAIN_SEEDS) -> UpperHMM:
    """Fit A + emissions from separately-seeded labelled training loops (the REPORTED model)."""
    obs_chunks: list[np.ndarray] = []
    all_labels: list[str] = []
    label_sequences: list[list[str]] = []
    for seed in seeds:
        trace = generate_loop(config, seed=seed)
        frames, labels = extract_frames(config, trace)
        obs_chunks.append(observation_matrix(frames))
        all_labels.extend(labels)
        label_sequences.append(labels)
    X = np.concatenate(obs_chunks, axis=0)
    A = UpperHMM.fit_transitions(label_sequences, laplace=1.0)
    emissions = UpperHMM.fit_emissions(X, all_labels, var_floor=1e-3)
    return UpperHMM(transition_matrix=A, emissions=emissions)


def _fresh_hmm(fitted: UpperHMM) -> UpperHMM:
    """A fresh HMM sharing the fitted A + emissions but with an independent belief."""
    return UpperHMM(transition_matrix=fitted.A, emissions=fitted.emissions)


def build_controller(name: str, config: dict, fitted: UpperHMM | None):
    """Construct a controller by its stable rung/ablation name.

    fitted may be None for the two model-free rungs (fixed_zone, dynamic_ssm).
    """
    sr = config["controller"]["speed_reduced"]
    lh = config["lhmm"]
    hz = config["horizon"]

    if name == "fixed_zone":
        return FixedZoneController(build_zone_model(config), speed_reduced=sr)
    if name == "dynamic_ssm":
        return DynamicSSMController(
            build_zone_model(config), envelope=build_envelope(config), speed_reduced=sr
        )
    if name not in ("adaptive", "adaptive_no_pred", "adaptive_no_state"):
        raise ValueError(f"unknown controller name: {name!r}")
    if fitted is None:
        raise ValueError(f"controller {name!r} needs a fitted HMM")

    return EnvelopeAdaptiveController(
        build_zone_model(config),
        _fresh_hmm(fitted),
        envelope=build_envelope(config),
        speed_reduced=sr,
        hazard_prob_threshold=lh["hazard_prob_threshold"],
        hazard_dwell_ticks=lh["hazard_dwell_ticks"],
        working_stability_ticks=config["controller"]["working_stability_ticks"],
        horizon_s=hz["horizon_s"],
        imminence_steepness=hz["imminence_steepness"],
        risk_threshold=hz["risk_threshold"],
        max_human_accel=hz["max_human_accel"],
        min_closing_speed=hz["min_closing_speed"],
        use_horizon=(name != "adaptive_no_pred"),
        use_state_layer=(name != "adaptive_no_state"),
        condition=name,
    )


def score_run(config: dict, run: RunResult, trace: LoopTrace) -> Metrics:
    """Score an already-executed run against the trace's ground truth (single run).

    Split out from `score` so the pipeline can run a controller ONCE and derive both the
    flat metrics and the per-phase metrics from the same records (controllers are stateful
    -- re-running the same instance would carry belief/streak state across the boundary).
    """
    return compute_metrics(
        run.records,
        run.labels,
        trace.dt,
        trace.hazard_onset_t,
        red_radius=build_zone_model(config).red_radius,
        slip_windows=trace.slip_windows,
        distractor_windows=trace.distractor_windows,
        robot_modes=run.robot_modes,
    )


def phase_metrics_from_run(run: RunResult, trace: LoopTrace) -> dict[str, PhaseMetrics]:
    """Per-phase metrics from an already-executed run (v2 measurement-window reporting)."""
    return compute_phase_metrics(
        run.records,
        run.phases,
        run.robot_modes,
        trace.dt,
        slip_windows=trace.slip_windows,
    )


def score(config: dict, controller, trace: LoopTrace) -> Metrics:
    """Run a controller over a trace and score it against the trace's ground truth."""
    return score_run(config, run_controller(config, controller, trace), trace)


def metrics_to_dict(m: Metrics) -> dict:
    """Plain-dict form of Metrics for JSON emission (feeds make_paper_tables.py)."""
    return asdict(m)


def phase_metrics_to_dict(pm: dict[str, PhaseMetrics]) -> dict:
    """Plain-dict form of per-phase metrics for JSON emission."""
    return {phase: asdict(m) for phase, m in pm.items()}
