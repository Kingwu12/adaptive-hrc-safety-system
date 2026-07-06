"""Experiment metrics and recognition report.

The controller is NEVER allowed to grade itself: 'unnecessary interruption' is
scored against GROUND-TRUTH labels (what the operator was actually doing), never
against the controller's own inferred state. A controller that mislabels a working
operator as hazardous must be PENALISED for the resulting interruption, not excused
by its own (wrong) belief.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .logging_schema import Command, DecisionRecord
from .lhmm.upper import STATES


def _is_stop(rec: DecisionRecord) -> bool:
    return rec.command == Command.PROTECTIVE_STOP.value


def _is_slowdown(rec: DecisionRecord) -> bool:
    return rec.command == Command.REDUCED_SPEED.value


def _episodes(flags: list[bool], dt: float) -> tuple[int, float]:
    """Count rising edges and total active duration for a boolean flag series."""
    count = 0
    duration = 0.0
    prev = False
    for f in flags:
        if f and not prev:
            count += 1
        if f:
            duration += dt
        prev = f
    return count, duration


@dataclass
class Metrics:
    min_separation: float
    stop_episodes: int
    stop_duration_s: float
    slowdown_episodes: int
    slowdown_duration_s: float
    unnecessary_interruption_s: float
    hazard_response_latency_s: float | None


def compute_metrics(
    records: list[DecisionRecord],
    gt_labels: list[str],
    dt: float,
    hazard_onset_t: float | None,
) -> Metrics:
    """Compute the head-to-head safety/efficiency metrics for one controller run."""
    if len(records) != len(gt_labels):
        raise ValueError("records and gt_labels must be the same length")

    min_sep = min((r.d for r in records), default=float("nan"))

    stop_flags = [_is_stop(r) for r in records]
    slow_flags = [_is_slowdown(r) for r in records]
    stop_episodes, stop_duration = _episodes(stop_flags, dt)
    slowdown_episodes, slowdown_duration = _episodes(slow_flags, dt)

    # Unnecessary interruption: robot interrupted (stop OR slowdown) while the
    # operator was -- per GROUND TRUTH -- merely working or retreating.
    productive = {"working", "retreating"}
    unnecessary_s = 0.0
    for rec, gt in zip(records, gt_labels):
        interrupted = _is_stop(rec) or _is_slowdown(rec)
        if interrupted and gt in productive:
            unnecessary_s += dt

    # Hazard response latency: from ground-truth hazard onset to first stop after it.
    latency: float | None = None
    if hazard_onset_t is not None:
        for rec in records:
            if rec.t >= hazard_onset_t and _is_stop(rec):
                latency = rec.t - hazard_onset_t
                break

    return Metrics(
        min_separation=float(min_sep),
        stop_episodes=stop_episodes,
        stop_duration_s=float(stop_duration),
        slowdown_episodes=slowdown_episodes,
        slowdown_duration_s=float(slowdown_duration),
        unnecessary_interruption_s=float(unnecessary_s),
        hazard_response_latency_s=latency,
    )


@dataclass
class RecognitionReport:
    accuracy: float
    confusion: np.ndarray  # (n_states, n_states); rows = true, cols = predicted
    hazard_precision: float
    hazard_recall: float
    states: tuple[str, ...] = field(default=STATES)


def recognition_report(
    predicted_states: list[str], gt_labels: list[str]
) -> RecognitionReport:
    """Accuracy, confusion matrix, and hazard precision/recall for the LHMM."""
    if len(predicted_states) != len(gt_labels):
        raise ValueError("predicted_states and gt_labels must be the same length")

    index = {s: i for i, s in enumerate(STATES)}
    n = len(STATES)
    confusion = np.zeros((n, n), dtype=int)
    correct = 0
    for pred, true in zip(predicted_states, gt_labels):
        confusion[index[true], index[pred]] += 1
        if pred == true:
            correct += 1
    accuracy = correct / len(gt_labels) if gt_labels else 0.0

    h = index["hazard"]
    tp = int(confusion[h, h])
    fp = int(confusion[:, h].sum() - tp)
    fn = int(confusion[h, :].sum() - tp)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    return RecognitionReport(
        accuracy=accuracy,
        confusion=confusion,
        hazard_precision=precision,
        hazard_recall=recall,
    )
