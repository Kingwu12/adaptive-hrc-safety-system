"""Synthetic 'Panel Cycle' generator (sem-2 v2 scenario).

IMPORTANT: this synthetic data is for DEVELOPMENT and PIPELINE VALIDATION ONLY.
It NEVER appears in reported results. Reported models are fitted from labelled
PILOT data collected in the lab (see docs/experiment_plan.md); synthetic traces
exist only to exercise the code path pilot data will follow.

THE TASK (v2). One repeating Panel Cycle of ceiling-panel installation, human + robot.
The robot is a lifting/holding jack with a releasable gripper/vacuum end-effector --
nothing is ever bolted to the robot. The human is loader, aligner, and bolter. The full
phase / collaborative-mode vocabulary lives in `hrc_safety.panel_cycle`. Five phases:

    P1 LOAD (monitored stop; NOT a measurement window)
        arm lowered to waist; the human slides the panel onto the plate at close range,
        arm parked. A distinct task state, not a primary measurement window.
    P2 TRANSIT_UP (SSM; MEASUREMENT WINDOW)
        the robot lifts the panel to the ceiling and aligns it flush WHILE the human
        remains in the shared workspace (fetching the bolt gun, repositioning the
        platform). Concurrent motion + proximity: static SSM forces the human out of the
        worst-case protective distance or protective-stops every cycle; adaptive shrinks
        the zone (measured low closing speed + recognised prep state) and permits work.
    P3 HAND_GUIDE (hand-guiding / compliant hold; MEASUREMENT WINDOW, max divergence)
        real panels never line up with the bolt holes, so the human nudges the
        compliantly-held panel a few millimetres BY HAND -- genuine contact. Static logic
        essentially forbids it (fixed-RED breach -> protective stop); adaptive permits it
        by honouring the CERTIFIED compliant-hold mode (never by the learned layer).
    P4 HOLD_BOLT (safety-rated monitored stop; EXPLICITLY NOT a measurement window)
        the human drives bolts through the panel INTO THE CEILING STRUCTURE while the
        robot holds dead still. Static and adaptive are IDENTICAL here.
    P5 RELEASE_RETRACT (SSM; MEASUREMENT WINDOW)
        the robot releases and lowers while the human finishes the last bolt / descends.
        Concurrent motion + proximity again.

GEOMETRY. Separation is measured to the robot's OCCUPIED COLUMN (the vertical install
volume the arm + panel sweep, ground up to the overhead TCP), not to a moving TCP point
-- so the geometry is stable across the lift and a human standing under the panel has ~0 m
of protective separation (see features.py). Stances are distances from that column:
    load_radius     -- P1, human at the end-effector plate (arm parked);
    prep_radius      -- P2/P5, tending stance inside the worst-case zone, low closing;
    contact_radius   -- P3/P4, human directly under the panel (near-contact);
    staging (bench)  -- DERIVED as yellow_radius + bench_clearance (a clean green exit).

WHY A SLIP + DISTRACTORS (sensitivity AND specificity, and why the certified MODE matters):
    The ONE true hazard is a simulated SLIP -- a fast lunge toward the column, breaching
    red, during P2 (SSM mode). Because it happens in SSM mode it MUST stop the robot
    (sensitivity). Contrast with P3 hand-guiding: the SAME small separation is SAFE there,
    because the certified mode is compliant hold -- proof that separation alone cannot
    decide, the collaborative mode must.
    Two cued DISTRACTORS are fast motions that are NOT hazards (ground-truth non-hazard),
    placed in the SSM measurement windows:
      (a) a fast LATERAL dart across the prep stance in P2 (fast, ~zero closing);
      (b) a sudden fast RETREAT away from the column in P5 (fast, opening).
    A good controller must NOT stop for them -- this is what lets us report SPECIFICITY
    (correctly not stopping) alongside sensitivity (correctly stopping for the slip).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..panel_cycle import CollaborativeMode, Phase

# Ground-truth activity labels (subset of the LHMM state set) -- what the HUMAN is doing.
# These are distinct from the cycle Phase and the robot's CollaborativeMode.
_APPROACH = "approaching"
_WORKING = "working"
_RETREAT = "retreating"
_HAZARD = "hazard"

_TORSO_Z = 1.4  # operator torso height (m); constant standing height

# Convenience aliases for the per-sample tags emitted below.
_SSM = CollaborativeMode.SSM.value
_HG = CollaborativeMode.HAND_GUIDE.value
_MS = CollaborativeMode.MONITORED_STOP.value


@dataclass
class LoopTrace:
    """One synthetic Panel Cycle: aligned samples, labels, phases, modes, and windows."""

    times: np.ndarray  # (T,)
    positions: np.ndarray  # (T, 3)
    labels: list[str]  # length T ground-truth activity (LHMM state)
    events: list[tuple[str, float]]  # (name, timestamp)
    dt: float
    hazard_onset_t: float  # ground-truth slip onset (== hazard-latency reference)
    # Ground-truth evaluation windows (start_t, end_t), in the SAME time base as
    # `times` -- which is also each DecisionRecord.t (frames carry the raw sample
    # time), so windows compare directly against rec.t with no shifting.
    slip_windows: list[tuple[float, float]] = field(default_factory=list)  # true hazard
    distractor_windows: list[tuple[float, float]] = field(default_factory=list)  # non-hazard fast
    # Per-sample cycle phase and certified robot collaborative mode (length T each).
    # Empty => a legacy/pilot trace with no phase structure; consumers treat every tick
    # as SSM and assign no phase.
    phases: list[str] = field(default_factory=list)
    robot_modes: list[str] = field(default_factory=list)
    # Convenience: phase -> list of (start_t, end_t) windows, derived from `phases`.
    phase_windows: dict[str, list[tuple[float, float]]] = field(default_factory=dict)


def _smoothstep(u: np.ndarray) -> np.ndarray:
    """Ease-in/out interpolation weight in [0,1]."""
    return 3.0 * u**2 - 2.0 * u**3


def _move(p0, p1, n_samples: int) -> np.ndarray:
    """Ease-in/out straight-line move from p0 to p1 over n_samples points."""
    p0 = np.asarray(p0, dtype=float)
    p1 = np.asarray(p1, dtype=float)
    u = np.linspace(0.0, 1.0, n_samples)
    w = _smoothstep(u)[:, None]
    return p0[None, :] + w * (p1 - p0)[None, :]


def _dwell(p, n_samples: int, sway_amp: float, rng, sway_axis) -> np.ndarray:
    """Stay at p with a lateral sinusoidal sway (models fastening / nudging motion)."""
    p = np.asarray(p, dtype=float)
    axis = np.asarray(sway_axis, dtype=float)
    axis = axis / (np.linalg.norm(axis) + 1e-9)
    phase = np.linspace(0.0, 2.0 * np.pi * 1.5, n_samples)
    offs = sway_amp * np.sin(phase)[:, None] * axis[None, :]
    return p[None, :] + offs


def generate_loop(config: dict, seed: int = 0) -> LoopTrace:
    """Generate one labelled Panel Cycle from the scenario config block.

    Different seeds give independently-noised cycles (used to build separate
    training traces and a held-out test trace).
    """
    rng = np.random.default_rng(seed)
    scn = config["scenario"]
    sample_rate = float(config["features"]["sample_rate_hz"])
    dt = 1.0 / sample_rate

    tcp = np.asarray(scn["tcp_position"], dtype=float)
    # Zone geometry has ONE owner (ZoneModel); the staging bench derives from its yellow.
    from ..config import build_zone_model

    zone_model = build_zone_model(config)
    load_r = float(scn["load_radius"])
    prep_r = float(scn["prep_radius"])
    contact_r = float(scn["contact_radius"])
    bench_r = zone_model.yellow_radius + float(scn["bench_clearance"])

    def stance(radius: float, angle_deg: float) -> np.ndarray:
        a = np.radians(angle_deg)
        return np.array(
            [tcp[0] + radius * np.cos(a), tcp[1] + radius * np.sin(a), _TORSO_Z]
        )

    staging = stance(bench_r, 0.0)   # green: fetch the next panel / stage tools
    load = stance(load_r, 0.0)       # P1: at the end-effector plate
    prep = stance(prep_r, 0.0)       # P2/P5: tending stance (inside worst-case zone)
    under = stance(contact_r, 0.0)   # P3/P4: directly under the panel (near-contact)
    slip_pt = stance(0.55, 0.0)      # breaches red (< S0); ~reference min separation

    sway = float(scn["work_sway_speed"]) * 0.25  # sway amplitude (m)
    tangent = np.array([0.0, 1.0, 0.0])  # lateral (tangent to the column at angle 0)

    def n(seconds: float) -> int:
        return max(2, int(round(seconds * sample_rate)))

    # Distractor kinematics: fast (>= slip-scale) but NOT closing on the column.
    dart_speed = float(scn.get("distractor_dart_speed", 2.0))
    retreat_speed = float(scn.get("distractor_retreat_speed", 2.0))
    dart_dist = 0.35  # lateral out-and-back amplitude (m)

    # The dart is truly tangential at prep (angle 0): radial is +x, tangent is +y, so a
    # +y dart has ~zero closing component and reads as lateral, not an approach.
    dart_pt = prep + dart_dist * tangent
    fast_retreat_pt = stance(bench_r, -18.0)  # sudden retreat straight out to staging radius

    # A segment carries: (positions, activity label, phase, robot mode, window tag).
    #   tag None -> ordinary; "slip" -> true hazard window; "distractor" -> non-hazard fast.
    segments: list[tuple[np.ndarray, str, str, str, str | None]] = []

    def add_move(p0, p1, seconds, label, phase, mode, tag=None):
        segments.append((_move(p0, p1, n(seconds)), label, phase, mode, tag))

    def add_dwell(p, seconds, label, phase, mode, tag=None):
        segments.append((_dwell(p, n(seconds), sway, rng, tangent), label, phase, mode, tag))

    P_LOAD = Phase.LOAD.value
    P_TRANSIT = Phase.TRANSIT_UP.value
    P_HG = Phase.HAND_GUIDE.value
    P_BOLT = Phase.HOLD_BOLT.value
    P_RETRACT = Phase.RELEASE_RETRACT.value

    # --- the Panel Cycle ----------------------------------------------------
    # P1 LOAD -- arm parked at waist; human slides the panel onto the plate. Not measured.
    add_move(staging, load, 1.4, _APPROACH, P_LOAD, _MS)
    add_dwell(load, 1.6, _WORKING, P_LOAD, _MS)             # slide panel onto the plate

    # P2 TRANSIT_UP -- robot lifts + aligns; human tends the shared workspace. MEASURE.
    add_move(load, prep, 1.0, _RETREAT, P_TRANSIT, _SSM)    # step back to the prep stance
    add_dwell(prep, 1.6, _WORKING, P_TRANSIT, _SSM)         # fetch bolt gun / reposition (sway)
    # DISTRACTOR (a): fast LATERAL dart across the prep stance -- fast, ~zero closing.
    add_move(prep, dart_pt, dart_dist / dart_speed, _WORKING, P_TRANSIT, _SSM, tag="distractor")
    add_move(dart_pt, prep, dart_dist / dart_speed, _WORKING, P_TRANSIT, _SSM, tag="distractor")
    # SIMULATED SLIP (lunge in, breaching red) -- the ONE true hazard, in SSM mode.
    add_move(prep, slip_pt, 0.5, _HAZARD, P_TRANSIT, _SSM, tag="slip")
    add_move(slip_pt, prep, 0.8, _RETREAT, P_TRANSIT, _SSM)  # recover outward

    # P3 HAND_GUIDE -- robot in certified compliant hold; human nudges the panel. MEASURE.
    # The step-in to contact is SLOW and deliberate (a hand-guide entry always is), so its
    # closing speed stays below the predictor's gate -- the learned layer adds no spurious
    # caution and hand-guiding is feasible for the envelope rungs at the compliant floor.
    add_move(prep, under, 4.0, _APPROACH, P_HG, _HG)        # slow, deliberate step-in
    add_dwell(under, 2.0, _WORKING, P_HG, _HG)              # nudge a few mm by hand (contact)

    # P4 HOLD_BOLT -- robot dead still (SMS); human bolts into the ceiling. NOT measured.
    add_dwell(under, 2.0, _WORKING, P_BOLT, _MS)

    # P5 RELEASE_RETRACT -- robot releases + lowers; human finishes / descends. MEASURE.
    # The robot stays in its monitored-stop HOLD until the human has cleared the protective
    # distance; only then does it release and lower under SSM. So the human clears red under
    # a held (motionless) robot -- the SSM-monitored separation never dips below the
    # protective distance during ordinary retract (only the cued P2 slip does).
    add_move(under, prep, 0.8, _RETREAT, P_RETRACT, _MS)    # step clear of red (robot held)
    # DISTRACTOR (b): sudden fast RETREAT under SSM -- fast, but OPENING (moving away).
    add_move(prep, fast_retreat_pt,
             (bench_r - prep_r) / retreat_speed, _RETREAT, P_RETRACT, _SSM, tag="distractor")
    add_move(fast_retreat_pt, staging, 0.8, _RETREAT, P_RETRACT, _SSM)  # robot lowers; settle

    # --- assemble, tracking events, ground-truth windows, phases, and modes -
    positions_chunks: list[np.ndarray] = []
    labels: list[str] = []
    phases: list[str] = []
    robot_modes: list[str] = []
    events: list[tuple[str, float]] = []
    slip_windows: list[tuple[float, float]] = []
    distractor_windows: list[tuple[float, float]] = []
    phase_windows: dict[str, list[tuple[float, float]]] = {}
    hazard_onset_t = 0.0
    idx = 0
    for chunk, label, phase, mode, tag in segments:
        start_t = idx * dt
        end_t = (idx + len(chunk)) * dt
        if tag == "slip":
            if not slip_windows:
                hazard_onset_t = start_t
                events.append(("slip_onset", hazard_onset_t))
            slip_windows.append((start_t, end_t))
        elif tag == "distractor":
            distractor_windows.append((start_t, end_t))
        phase_windows.setdefault(phase, []).append((start_t, end_t))
        positions_chunks.append(chunk)
        labels.extend([label] * len(chunk))
        phases.extend([phase] * len(chunk))
        robot_modes.extend([mode] * len(chunk))
        idx += len(chunk)

    positions = np.concatenate(positions_chunks, axis=0)
    # Sensor jitter (independent per axis) -- makes the velocity/accel slopes work.
    positions = positions + rng.normal(0.0, 0.004, size=positions.shape)
    times = np.arange(len(positions), dtype=float) * dt

    events.append(("loop_end", float(times[-1])))
    return LoopTrace(
        times=times,
        positions=positions,
        labels=labels,
        events=events,
        dt=dt,
        hazard_onset_t=hazard_onset_t,
        slip_windows=slip_windows,
        distractor_windows=distractor_windows,
        phases=phases,
        robot_modes=robot_modes,
        phase_windows=phase_windows,
    )
