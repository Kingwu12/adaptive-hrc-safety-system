"""Synthetic 'Multi-Point Alignment & Tool-Retrieval Loop' generator.

IMPORTANT: this synthetic data is for DEVELOPMENT and PIPELINE VALIDATION ONLY.
It NEVER appears in reported results. Reported models are fitted from labelled
PILOT data collected in the lab (see docs/experiment_plan.md); synthetic traces
exist only to exercise the code path pilot data will follow.

The loop, with per-sample ground-truth labels:
    bench dwell -> approach -> fasten L (lateral sway) -> shuffle to R ->
    fasten R -> retreat to bench -> approach -> fasten -> SIMULATED SLIP
    (rapid lunge toward the robot column, breaching red) -> recover -> final retreat.

Geometry (all distances are to the robot's occupied column, at the origin in xy):
    fastening stances sit at work_radius (inside yellow, outside red);
    the bench is DERIVED as yellow_radius + bench_clearance, so the retreat to the
    bench produces a clean exit through both zone boundaries for the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Ground-truth activity labels (subset of the LHMM state set).
_APPROACH = "approaching"
_WORKING = "working"
_RETREAT = "retreating"
_HAZARD = "hazard"

_TORSO_Z = 1.4  # operator torso height (m); constant standing height


@dataclass
class LoopTrace:
    """One synthetic loop: aligned samples, labels, and event timestamps."""

    times: np.ndarray  # (T,)
    positions: np.ndarray  # (T, 3)
    labels: list[str]  # length T ground-truth activity
    events: list[tuple[str, float]]  # (name, timestamp)
    dt: float
    hazard_onset_t: float  # ground-truth slip onset (== hazard-latency reference)


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
    """Stay at p with a lateral sinusoidal sway (models fastening motion)."""
    p = np.asarray(p, dtype=float)
    axis = np.asarray(sway_axis, dtype=float)
    axis = axis / (np.linalg.norm(axis) + 1e-9)
    phase = np.linspace(0.0, 2.0 * np.pi * 1.5, n_samples)
    offs = sway_amp * np.sin(phase)[:, None] * axis[None, :]
    return p[None, :] + offs


def generate_loop(config: dict, seed: int = 0) -> LoopTrace:
    """Generate one labelled loop from the scenario config block.

    Different seeds give independently-noised loops (used to build separate
    training traces and a held-out test trace).
    """
    rng = np.random.default_rng(seed)
    scn = config["scenario"]
    sample_rate = float(config["features"]["sample_rate_hz"])
    dt = 1.0 / sample_rate

    tcp = np.asarray(scn["tcp_position"], dtype=float)
    work_r = float(scn["work_radius"])
    # Zone geometry has ONE owner (ZoneModel); the bench derives from its yellow radius.
    from ..config import build_zone_model

    zone_model = build_zone_model(config)
    bench_r = zone_model.yellow_radius + float(scn["bench_clearance"])

    def stance(radius: float, angle_deg: float) -> np.ndarray:
        a = np.radians(angle_deg)
        return np.array(
            [tcp[0] + radius * np.cos(a), tcp[1] + radius * np.sin(a), _TORSO_Z]
        )

    bench = stance(bench_r, 0.0)
    fasten_l = stance(work_r, 22.0)
    fasten_r = stance(work_r, -22.0)
    fasten_c = stance(work_r, 0.0)
    slip_pt = stance(0.55, 0.0)  # breaches red (< S0); ~reference min separation

    sway = float(scn["work_sway_speed"]) * 0.25  # sway amplitude (m)
    # Sway laterally (tangent to the column), i.e. perpendicular to the radius.
    tangent = np.array([0.0, 1.0, 0.0])

    def n(seconds: float) -> int:
        return max(2, int(round(seconds * sample_rate)))

    segments: list[tuple[np.ndarray, str]] = []

    def add_move(p0, p1, seconds, label):
        segments.append((_move(p0, p1, n(seconds)), label))

    def add_dwell(p, seconds, label):
        segments.append((_dwell(p, n(seconds), sway, rng, tangent), label))

    # --- the loop -----------------------------------------------------------
    add_dwell(bench, 1.2, _WORKING)               # bench dwell (tool retrieval)
    add_move(bench, fasten_l, 1.6, _APPROACH)     # approach the work face
    add_dwell(fasten_l, 2.6, _WORKING)            # fasten L (with sway)
    add_move(fasten_l, fasten_r, 1.1, _WORKING)   # shuffle L -> R (lateral)
    add_dwell(fasten_r, 2.6, _WORKING)            # fasten R
    add_move(fasten_r, bench, 1.6, _RETREAT)      # retreat to bench
    add_move(bench, fasten_c, 1.6, _APPROACH)     # approach again
    add_dwell(fasten_c, 1.8, _WORKING)            # fasten (centre)
    slip_seg = _move(fasten_c, slip_pt, n(0.5))   # SIMULATED SLIP (lunge in)
    segments.append((slip_seg, _HAZARD))
    add_move(slip_pt, fasten_c, 0.8, _RETREAT)    # recover outward
    add_move(fasten_c, bench, 1.7, _RETREAT)      # final retreat

    # --- assemble, tracking the slip onset timestamp ------------------------
    positions_chunks: list[np.ndarray] = []
    labels: list[str] = []
    events: list[tuple[str, float]] = []
    hazard_onset_t = 0.0
    idx = 0
    for chunk, label in segments:
        if label == _HAZARD and not events:
            hazard_onset_t = idx * dt
            events.append(("slip_onset", hazard_onset_t))
        positions_chunks.append(chunk)
        labels.extend([label] * len(chunk))
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
    )
