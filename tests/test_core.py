"""Core unit + smoke tests for the HRC safety pipeline.

The single most important test here is
test_red_zone_always_stops_adaptive_even_if_model_says_working: it locks the safety
invariant (RED breach => protective stop regardless of model belief). It is a
PERMANENT MERGE BLOCKER -- never weaken it.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.config import build_zone_model, load_config
from hrc_safety.controllers import AdaptiveController, StaticController
from hrc_safety.features import FeatureExtractor, FeatureFrame
from hrc_safety.lhmm.upper import STATES, GaussianEmissions, UpperHMM
from hrc_safety.logging_schema import Command
from hrc_safety.prediction import predict_next
from hrc_safety.sim.runner import run_controller
from hrc_safety.sim.scenario import generate_loop
from hrc_safety.zones import Zone, ZoneModel


# --- fixtures / helpers ----------------------------------------------------

_ZONE_KW = dict(K=1.6, T=0.40, C=0.20, Sa=0.10, yellow_margin=1.6, hysteresis=0.05)


def _zone_model() -> ZoneModel:
    return ZoneModel(**_ZONE_KW)


def _frame(d: float, v_proj: float = 0.0, v_lat_frac: float = 0.0, a_proj: float = 0.0,
           t: float = 0.0) -> FeatureFrame:
    speed = abs(v_proj) + abs(v_lat_frac)
    return FeatureFrame(
        t=t, d=d, d_dot=-v_proj, speed=speed, v_proj=v_proj,
        v_lat_frac=v_lat_frac, a_proj=a_proj, torso_facing=1.0,
    )


def _forced_hmm(target_state: str, obs: np.ndarray) -> UpperHMM:
    """Build an HMM whose emissions make `target_state` the certain argmax for obs."""
    n = len(STATES)
    means = np.full((n, obs.shape[0]), 100.0)
    variances = np.full((n, obs.shape[0]), 0.01)
    means[STATES.index(target_state)] = obs
    emissions = GaussianEmissions(means=means, variances=variances)
    A = np.full((n, n), 1.0 / n)  # uniform, valid transitions
    return UpperHMM(transition_matrix=A, emissions=emissions)


def _adaptive(zone_model: ZoneModel, hmm: UpperHMM) -> AdaptiveController:
    return AdaptiveController(
        zone_model, hmm, speed_reduced=0.35,
        hazard_prob_threshold=0.35, hazard_dwell_ticks=2, working_stability_ticks=30,
    )


# --- 1. S0 formula ---------------------------------------------------------

def test_s0_formula():
    z = _zone_model()
    assert z.S0 == pytest.approx(1.6 * 0.40 + 0.20 + 0.10)  # 0.94
    assert z.red_radius == pytest.approx(0.94)
    assert z.yellow_radius == pytest.approx(1.6 * 0.94)  # 1.504


# --- 2. zone entry is immediate --------------------------------------------

def test_zone_entry_is_immediate():
    z = _zone_model()
    assert z.zone == Zone.GREEN
    assert z.update(1.2) == Zone.YELLOW      # green -> yellow immediately
    assert z.update(0.5) == Zone.RED         # yellow -> red immediately


# --- 3. zone exit is hysteretic --------------------------------------------

def test_zone_exit_is_hysteretic():
    z = _zone_model()
    z.update(0.5)  # in RED
    # Just past the red boundary but within the hysteresis band -> stay RED.
    assert z.update(z.red_radius + 0.02) == Zone.RED
    # Clear the boundary + band -> leave to YELLOW.
    assert z.update(z.red_radius + 0.10) == Zone.YELLOW
    # Just past the yellow boundary within the band -> stay YELLOW.
    assert z.update(z.yellow_radius + 0.02) == Zone.YELLOW
    # Clear yellow + band -> GREEN.
    assert z.update(z.yellow_radius + 0.10) == Zone.GREEN


# --- 4. prediction equals paper Eq.1 ---------------------------------------

def test_prediction_equals_eq1():
    p = np.array([0.4, 0.3, 0.2, 0.1])
    A = np.array([
        [0.7, 0.1, 0.1, 0.1],
        [0.2, 0.6, 0.1, 0.1],
        [0.1, 0.1, 0.7, 0.1],
        [0.25, 0.25, 0.25, 0.25],
    ])
    expected = p @ A
    expected = expected / expected.sum()
    np.testing.assert_allclose(predict_next(p, A), expected)


# --- 5. fitted transitions rows sum to 1 -----------------------------------

def test_fit_transitions_rows_sum_to_one():
    seqs = [
        ["approaching", "approaching", "working", "working", "retreating"],
        ["working", "working", "hazard", "retreating", "retreating"],
    ]
    A = UpperHMM.fit_transitions(seqs, laplace=1.0)
    assert A.shape == (4, 4)
    np.testing.assert_allclose(A.sum(axis=1), np.ones(4))


# --- 6. THE PERMANENT MERGE BLOCKER ----------------------------------------

def test_red_zone_always_stops_adaptive_even_if_model_says_working():
    """RED breach => protective stop, even when the model is certain it's 'working'."""
    obs = np.array([0.30, 0.0, 0.9, 0.0])  # working-like kinematics, but d in RED
    hmm = _forced_hmm("working", obs)
    ctrl = _adaptive(_zone_model(), hmm)

    frame = _frame(d=0.30, v_proj=0.0, v_lat_frac=0.9, a_proj=0.0)
    rec = ctrl.decide(frame)

    # The model really does believe 'working'...
    assert rec.inferred_state == "working"
    # ...and it stops anyway.
    assert rec.command == Command.PROTECTIVE_STOP.value
    assert rec.speed_fraction == 0.0
    assert "SAFETY INVARIANT" in rec.rule


# --- 7. static zone mapping ------------------------------------------------

def test_static_zone_mapping():
    ctrl = StaticController(_zone_model(), speed_reduced=0.35)
    assert ctrl.decide(_frame(d=2.0)).command == Command.FULL_SPEED.value      # green
    assert ctrl.decide(_frame(d=1.2)).command == Command.REDUCED_SPEED.value   # yellow
    assert ctrl.decide(_frame(d=0.5)).command == Command.PROTECTIVE_STOP.value # red


# --- 8. adaptive full speed when retreating in yellow ----------------------

def test_adaptive_full_speed_when_retreating_in_yellow():
    obs = np.array([1.20, -0.6, 0.15, -0.2])  # retreating kinematics in the yellow band
    hmm = _forced_hmm("retreating", obs)
    ctrl = _adaptive(_zone_model(), hmm)

    rec = None
    for i in range(5):  # sustained retreat frames
        rec = ctrl.decide(_frame(d=1.20, v_proj=-0.6, v_lat_frac=0.15, a_proj=-0.2, t=i))
    assert rec.inferred_state == "retreating"
    assert rec.command == Command.FULL_SPEED.value  # the efficiency win
    assert rec.speed_fraction == 1.0


# --- 9. v_proj sign convention ---------------------------------------------

def test_v_proj_sign_convention_closing_positive():
    ext = FeatureExtractor(tcp_position=[0.0, 0.0, 2.2], sample_rate_hz=60.0)
    dt = 1.0 / 60.0
    frame = None
    for i in range(6):  # operator walks straight toward the column at 1 m/s
        x = 2.0 - 1.0 * (i * dt)
        frame = ext.push(i * dt, [x, 0.0, 1.4])
    assert frame is not None
    assert frame.v_proj > 0.0   # closing => positive
    assert frame.d_dot < 0.0    # distance shrinking


# --- 10. end-to-end smoke: the slip produces a protective stop -------------

def test_end_to_end_slip_forces_stop():
    config = load_config()

    # Fit a model from a couple of training loops (same procedure as the script).
    from hrc_safety.sim.runner import extract_frames, observation_matrix

    obs_chunks, all_labels, seqs = [], [], []
    for seed in (11, 22):
        tr = generate_loop(config, seed=seed)
        frames, labels = extract_frames(config, tr)
        obs_chunks.append(observation_matrix(frames))
        all_labels.extend(labels)
        seqs.append(labels)
    A = UpperHMM.fit_transitions(seqs)
    emissions = UpperHMM.fit_emissions(np.concatenate(obs_chunks), all_labels)
    hmm = UpperHMM(transition_matrix=A, emissions=emissions)

    test_trace = generate_loop(config, seed=7)

    static = StaticController(build_zone_model(config),
                              speed_reduced=config["controller"]["speed_reduced"])
    adaptive = _adaptive(build_zone_model(config), hmm)

    static_run = run_controller(config, static, test_trace)
    adaptive_run = run_controller(config, adaptive, test_trace)

    # The simulated slip breaches the red zone -> both controllers must stop.
    assert any(r.command == Command.PROTECTIVE_STOP.value for r in static_run.records)
    assert any(r.command == Command.PROTECTIVE_STOP.value for r in adaptive_run.records)

    # Minimum separation dips below the red radius (the slip really breaches red).
    min_sep = min(r.d for r in adaptive_run.records)
    assert min_sep < build_zone_model(config).red_radius
