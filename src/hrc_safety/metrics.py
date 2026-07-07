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
from .panel_cycle import PHASES, CollaborativeMode, is_measurement_window

_SSM = CollaborativeMode.SSM.value
_MONITORED_STOP_MODE = CollaborativeMode.MONITORED_STOP.value


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
    robot_modes: list[str] | None = None,
) -> Metrics:
    """Compute the head-to-head safety/efficiency metrics for one controller run.

    red_radius / slip_windows / distractor_windows enable the sem-2 metrics; when
    omitted, those fields come back as None so callers with only a sem-1 trace still
    work.

    robot_modes (v2, optional): the certified collaborative mode per record. When given,
    MINIMUM SEPARATION is measured only over SSM-mode ticks -- the phases where separation
    is a genuine safety quantity. In hand-guiding / monitored-stop the human is at the
    panel by design (~0 m), so including those ticks would report a spurious "breach"
    every cycle. With no modes supplied, min separation is over all ticks (sem-1 behaviour).
    """
    if len(records) != len(gt_labels):
        raise ValueError("records and gt_labels must be the same length")
    slip_windows = slip_windows or []
    distractor_windows = distractor_windows or []

    if robot_modes is not None:
        if len(robot_modes) != len(records):
            raise ValueError("robot_modes and records must be the same length")
        ssm_d = [r.d for r, m in zip(records, robot_modes) if m == _SSM]
        # Fall back to all ticks only if the run never entered SSM (defensive).
        min_sep = min(ssm_d, default=min((r.d for r in records), default=float("nan")))
    else:
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
    #
    # v2: burden is measured over SSM OPERATION ONLY (when robot_modes is supplied). In
    # hand-guiding the compliant-hold reduced speed is INTENDED, and in monitored-stop the
    # robot is meant to be still -- charging those deficits would repeat the exact
    # category error the metric was frozen to avoid (penalising a controller for doing what
    # the task prescribes). So the burden isolates unwarranted caution during the
    # speed-and-separation phases (P2 transit, P5 retract), where contextual reasoning is
    # what actually differs between controllers. With no modes supplied (a sem-1 trace),
    # every tick counts as before.
    burden = 0.0
    for i, rec in enumerate(records):
        if robot_modes is not None and robot_modes[i] != _SSM:
            continue  # non-SSM mode: the reduced/stopped command is intended, not burden
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
class PhaseMetrics:
    """Per-phase outcome for one controller run (v2 Panel Cycle).

    Reporting per phase is what lets the measurement windows (P2 transit, P3 hand-guide,
    P5 retract) be read SEPARATELY from the P4 bolt HOLD -- where static and adaptive are
    identical and which is explicitly NOT a measurement window. Measuring that hold was
    the exact confusion the v2 redesign resolved.
    """

    phase: str
    collaborative_mode: str            # dominant certified robot mode in this phase
    is_measurement_window: bool
    duration_s: float                  # phase cycle time (wall time spent in the phase)
    min_separation: float              # min d in-phase (a safety quantity only in SSM windows)
    stop_episodes: int                 # protective-stop count (rising edges) in-phase
    stop_duration_s: float
    slowdown_duration_s: float
    speed_deficit_s: float             # time-integrated (1 - commanded speed) over the phase
    human_idle_s: float                # robot-stop time that blocks the human (0 outside
                                       # measurement windows and during warranted slip stops)


def _dominant(values: list[str]) -> str:
    """The most frequent string in a list ("" if empty)."""
    if not values:
        return ""
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get)


def compute_phase_metrics(
    records: list[DecisionRecord],
    phases: list[str],
    robot_modes: list[str],
    dt: float,
    *,
    slip_windows: list[tuple[float, float]] | None = None,
) -> dict[str, PhaseMetrics]:
    """Per-phase metrics keyed by phase name, for the v2 measurement-window reporting.

    `phases` / `robot_modes` are aligned one-to-one with `records` (see runner.RunResult).
    Phases are reported in the canonical P1->P5 order; any phase absent from the run is
    skipped. `human_idle_s` counts protective-stop time only in measurement-window phases
    and only outside true-hazard (slip) windows -- a warranted stop for a real slip, and
    the intended SMS hold in P4, are not "idle waiting".
    """
    if not (len(records) == len(phases) == len(robot_modes)):
        raise ValueError("records, phases, and robot_modes must be the same length")
    slip_windows = slip_windows or []

    by_phase: dict[str, list[tuple[DecisionRecord, str]]] = {}
    for rec, phase, mode in zip(records, phases, robot_modes):
        by_phase.setdefault(phase, []).append((rec, mode))

    out: dict[str, PhaseMetrics] = {}
    for phase in PHASES:
        rows = by_phase.get(phase)
        if not rows:
            continue
        recs = [r for r, _ in rows]
        modes = [m for _, m in rows]
        measurement = is_measurement_window(phase)

        stop_flags = [_is_stop(r) for r in recs]
        slow_flags = [_is_slowdown(r) for r in recs]
        stop_episodes, stop_duration = _episodes(stop_flags, dt)
        _, slowdown_duration = _episodes(slow_flags, dt)

        deficit = sum((1.0 - float(r.speed_fraction)) * dt for r in recs)

        # Minimum separation is a safety quantity only over SSM ticks: in hand-guiding /
        # monitored-stop the human is at the panel by design, so those ticks are excluded
        # (nan if the phase has no SSM ticks -- separation simply is not the metric there).
        ssm_d = [r.d for r, m in zip(recs, modes) if m == _SSM]
        min_sep = min(ssm_d, default=float("nan"))

        # Human idle = the robot stopping when it need not, in a measurement window. It
        # EXCLUDES monitored-stop holds (the stop is intended, not waiting) and true-hazard
        # (slip) windows (a warranted safety stop). What remains is SSM nuisance stops and
        # hand-guiding infeasibility -- the real time the human loses to the controller.
        idle = 0.0
        if measurement:
            for rec, mode in zip(recs, modes):
                if (
                    _is_stop(rec)
                    and mode != _MONITORED_STOP_MODE
                    and not _in_windows(rec.t, slip_windows)
                ):
                    idle += dt

        out[phase] = PhaseMetrics(
            phase=phase,
            collaborative_mode=_dominant(modes),
            is_measurement_window=measurement,
            duration_s=len(recs) * dt,
            min_separation=min_sep,
            stop_episodes=stop_episodes,
            stop_duration_s=float(stop_duration),
            slowdown_duration_s=float(slowdown_duration),
            speed_deficit_s=float(deficit),
            human_idle_s=float(idle),
        )
    return out


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
