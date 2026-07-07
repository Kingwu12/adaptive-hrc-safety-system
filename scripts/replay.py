#!/usr/bin/env python3
"""Offline REPLAY -- run any controller over a logged trace and emit metrics.

WHY THIS EXISTS (the free ablation machinery):
    The three rungs and the two ablations are all just "some controller over the SAME
    trace". Once a trace (positions + ground-truth labels + slip/distractor windows) is
    on disk, running another controller over it is free -- no robot, no re-collection.
    That is how we decompose the system: hold the trace fixed and swap one ingredient
    (speed-awareness, the state layer, prediction) to read off what each one buys. It
    is also how PILOT data will be scored: drop the recorded trace in, replay every
    rung, done.

USAGE
    # replay every rung/ablation over a fresh synthetic trace (pipeline check):
    python scripts/replay.py --seed 7 --controller all --out data/analysis/replay.json

    # save a trace, then replay a single controller over it:
    python scripts/replay.py --seed 7 --save-trace data/logs/trace7.npz
    python scripts/replay.py --trace data/logs/trace7.npz --controller adaptive

TRACE FILE FORMAT (.npz), so real pilot data can be dropped in the same shape:
    times (T,), positions (T,3), labels (T,) str, dt (), hazard_onset_t (),
    slip_windows (S,2), distractor_windows (D,2),
    phases (T,) str, robot_modes (T,) str      # v2 Panel Cycle phase + certified mode.

NOTE: synthetic traces are for pipeline validation only and never appear in reported
results (see docs/experiment_plan.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.analysis import (  # noqa: E402
    ABLATIONS,
    RUNGS,
    build_controller,
    fit_hmm,
    metrics_to_dict,
    score,
)
from hrc_safety.config import load_config  # noqa: E402
from hrc_safety.sim.scenario import LoopTrace, generate_loop  # noqa: E402

# All addressable controllers (rungs + ablations), de-duplicated, in a stable order.
ALL_CONTROLLERS = list(dict.fromkeys(RUNGS + ABLATIONS))


def save_trace(path: str, trace: LoopTrace) -> None:
    """Persist a LoopTrace as an .npz so it can be replayed later or shared."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    np.savez(
        path,
        times=trace.times,
        positions=trace.positions,
        labels=np.array(trace.labels, dtype=object),
        dt=np.array(trace.dt),
        hazard_onset_t=np.array(trace.hazard_onset_t),
        slip_windows=np.array(trace.slip_windows, dtype=float).reshape(-1, 2),
        distractor_windows=np.array(trace.distractor_windows, dtype=float).reshape(-1, 2),
        phases=np.array(trace.phases, dtype=object),
        robot_modes=np.array(trace.robot_modes, dtype=object),
    )


def load_trace(path: str) -> LoopTrace:
    """Load a LoopTrace from an .npz written by save_trace (or matching pilot data)."""
    z = np.load(path, allow_pickle=True)
    # Phases/modes are optional for backward compatibility with pre-v2 saved traces.
    phases = [str(x) for x in z["phases"]] if "phases" in z.files else []
    robot_modes = [str(x) for x in z["robot_modes"]] if "robot_modes" in z.files else []
    return LoopTrace(
        times=z["times"],
        positions=z["positions"],
        labels=[str(x) for x in z["labels"]],
        events=[],
        dt=float(z["dt"]),
        hazard_onset_t=float(z["hazard_onset_t"]),
        slip_windows=[tuple(w) for w in z["slip_windows"]],
        distractor_windows=[tuple(w) for w in z["distractor_windows"]],
        phases=phases,
        robot_modes=robot_modes,
    )


def _needs_model(names: list[str]) -> bool:
    return any(n not in ("fixed_zone", "dynamic_ssm") for n in names)


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay controllers over a logged trace.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--seed", type=int, default=7, help="generate a synthetic trace with this seed")
    src.add_argument("--trace", type=str, help="load a trace .npz instead of generating one")
    ap.add_argument(
        "--controller", default="all",
        help=f"one of {ALL_CONTROLLERS} or 'all' (default: all)",
    )
    ap.add_argument("--out", type=str, help="write metrics JSON to this path")
    ap.add_argument("--save-trace", type=str, help="save the (generated) trace to this .npz and exit")
    args = ap.parse_args()

    config = load_config()

    if args.trace:
        trace = load_trace(args.trace)
    else:
        trace = generate_loop(config, seed=args.seed)

    if args.save_trace:
        save_trace(args.save_trace, trace)
        print(f"Trace saved to {args.save_trace}")
        return

    if args.controller == "all":
        names = ALL_CONTROLLERS
    elif args.controller in ALL_CONTROLLERS:
        names = [args.controller]
    else:
        ap.error(f"unknown controller {args.controller!r}; choose from {ALL_CONTROLLERS} or 'all'")

    # Fit the model once only if some requested controller needs it.
    fitted = fit_hmm(config) if _needs_model(names) else None

    results = {}
    for name in names:
        controller = build_controller(name, config, fitted)
        m = metrics_to_dict(score(config, controller, trace))
        results[name] = m
        print(
            f"{name:18s} burden={m['interruption_burden_s']:6.3f}s  "
            f"sens={_fmt(m['hazard_sensitivity'])} spec={_fmt(m['hazard_specificity'])} "
            f"false_stop={_fmt(m['false_stop_rate'])} "
            f"lead={_fmt(m['anticipation_lead_time_s'])}s"
        )

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"source": "SYNTHETIC (replay, not reported)", "metrics": results}, fh, indent=2)
        print(f"\nMetrics JSON written to {args.out}")


def _fmt(v) -> str:
    return "n/a" if v is None else f"{v:.3f}"


if __name__ == "__main__":
    main()
