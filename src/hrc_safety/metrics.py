"""Experiment metrics and recognition report.

The controller is NEVER allowed to grade itself: outcomes are scored against
GROUND-TRUTH labels and windows (what the operator was actually doing), never against
the controller's own inferred state. A controller that mislabels a working operator as
hazardous must be PENALISED for the resulting interruption, not excused by its own
(wrong) belief.

SEM-2 PRIMARY EFFICIENCY OUTCOME -- interruption_burden (frozen; resolves the Table-I
contradiction, option (a)):
    The sem-1 primary metric ("unnecessary interruption") counted any stop OR slowdown
    while the operator was working/retreating -- but Table I PRESCRIBES a slowdown for a
    working operator in the yellow band, so the adaptive controller was charged for doing
    exactly what it was designed to do. The metric contradicted the design.

    The frozen primary is now interruption_burden: the time-integrated SPEED DEFICIT
    (full speed minus commanded speed) during GROUND-TRUTH-SAFE periods, where 'safe'
    EXCLUDES true-hazard (slip) windows and red-zone occupancy. Every condition is
    charged the SAME way for a given true situation, so a zone-consistent reduced speed
    while Working counts toward burden equally for all controllers -- the comparison
    therefore isolates CONTEXTUAL REASONING (who reduces speed when they needn't), not
    who happens to follow a fixed rule table. Lower burden = less lost productivity.

    The old count metrics (stop/slowdown episodes, unnecessary_interruption_s) are kept
    as SECONDARY, for continuity with the sem-1 tables.
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


def _in_windows(t: float, windows: list[tuple[float, float]]) -> bool:
    """True if timestamp t falls inside any [start, end) ground-truth window."""
    return any(start <= t < end for start, end in windows)


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
    # --- PRIMARY (sem-2) -------------------------------------------------------
    interruption_burden_s: float  # time-integrated speed deficit over ground-truth-safe time
    # --- hazard sensitivity / specificity (sem-2) ------------------------------
    hazard_sensitivity: float | None  # fraction of slip windows correctly stopped in
    hazard_specificity: float | None  # fraction of distractor windows correctly NOT stopped in
    false_stop_rate: float | None     # fraction of distractor TICKS with a stop commanded
    anticipation_lead_time_s: float | None  # slip-breach time minus stop-command time (>0 = pre-empted)
    # --- SECONDARY (sem-1 continuity) -----------------------------------------
    min_separation: float
    stop_episodes: int
    stop_duration_s: float
    slowdown_episodes: int
    slowdown_duration_s: float
    unnecessary_interruption_s: float
    hazard_response_latency_s: float | None


def _breach_time(records: list[DecisionRecord], red_radius: float) -> float | None:
    """First timestamp the operator actually crosses the red radius (d <= red_radius)."""
    for rec in records:
        if rec.d <= red_radius:
            return rec.t
    return None


def compute_metrics(
    records: list[DecisionRecord],
    gt_labels: list[str],
    dt: float,
    hazard_onset_t: float | None,
    *,
    red_radius: float | None = None,
    slip_windows: list[tuple[float, float]] | None = None,
    distractor_windows: list[tuple[float, float]] | None = None,
) -> Metrics:
    """Compute the head-to-head safety/efficiency metrics for one controller run.

    red_radius / slip_windows / distractor_windows enable the sem-2 metrics; when
    omitted, those fields come back as None so callers with only a sem-1 trace still
    work.
    """
    if len(records) != len(gt_labels):
        raise ValueError("records and gt_labels must be the same length")
    slip_windows = slip_windows or []
    distractor_windows = distractor_windows or []

    min_sep = min((r.d for r in records), default=float("nan"))

    stop_flags = [_is_stop(r) for r in records]
    slow_flags = [_is_slowdown(r) for r in records]
    stop_episodes, stop_duration = _episodes(stop_flags, dt)
    slowdown_episodes, slowdown_duration = _episodes(slow_flags, dt)

    # --- PRIMARY: interruption_burden -----------------------------------------
    # Integrate the speed deficit (1 - commanded speed) over GROUND-TRUTH-SAFE ticks.
    # 'Safe' excludes true-hazard (slip) windows and red-zone occupancy: slowing or
    # stopping there is CORRECT and must not be charged as burden. Every controller is
    # scored against the SAME ground truth, so the metric isolates who is cautious when
    # they need not be.
    burden = 0.0
    for rec in records:
        in_hazard = _in_windows(rec.t, slip_windows)
        in_red = (red_radius is not None and rec.d <= red_radius)
        if in_hazard or in_red:
            continue  # not a safe period; deficit here is warranted, not burden
        burden += (1.0 - float(rec.speed_fraction)) * dt

    # --- SECONDARY: sem-1 unnecessary interruption (kept for continuity) -------
    productive = {"working", "retreating"}
    unnecessary_s = 0.0
    for rec, gt in zip(records, gt_labels):
        interrupted = _is_stop(rec) or _is_slowdown(rec)
        if interrupted and gt in productive:
            unnecessary_s += dt

    # --- hazard SENSITIVITY: did we stop inside each true slip window? ---------
    sensitivity: float | None = None
    if slip_windows:
        hits = 0
        for start, end in slip_windows:
            if any(start <= r.t < end and _is_stop(r) for r in records):
                hits += 1
        sensitivity = hits / len(slip_windows)

    # --- hazard SPECIFICITY + false-stop rate on distractor windows -----------
    specificity: float | None = None
    false_stop_rate: float | None = None
    if distractor_windows:
        clean = 0
        distractor_ticks = 0
        stop_ticks = 0
        for start, end in distractor_windows:
            window_recs = [r for r in records if start <= r.t < end]
            distractor_ticks += len(window_recs)
            stops_here = [r for r in window_recs if _is_stop(r)]
            stop_ticks += len(stops_here)
            if not stops_here:
                clean += 1
        specificity = clean / len(distractor_windows)
        false_stop_rate = (stop_ticks / distractor_ticks) if distractor_ticks else 0.0

    # --- anticipation lead time: breach time minus first stop-after-onset ------
    # Positive => the robot stopped BEFORE the operator crossed the red radius (the
    # prediction bought lead time). A fixed/static controller only reacts on the breach
    # itself, so its lead time is <= 0 by construction.
    lead_time: float | None = None
    latency: float | None = None
    if hazard_onset_t is not None:
        stop_t: float | None = None
        for rec in records:
            if rec.t >= hazard_onset_t and _is_stop(rec):
                stop_t = rec.t
                latency = rec.t - hazard_onset_t
                break
        if red_radius is not None and stop_t is not None:
            breach_t = _breach_time(
                [r for r in records if r.t >= hazard_onset_t], red_radius
            )
            if breach_t is not None:
                lead_time = breach_t - stop_t

    return Metrics(
        interruption_burden_s=float(burden),
        hazard_sensitivity=sensitivity,
        hazard_specificity=specificity,
        false_stop_rate=false_stop_rate,
        anticipation_lead_time_s=lead_time,
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
