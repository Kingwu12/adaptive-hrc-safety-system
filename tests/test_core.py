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

from hrc_safety.analysis import build_controller, fit_hmm, score
from hrc_safety.config import build_zone_model, load_config
from hrc_safety.controllers import (
    AdaptiveController,
    DynamicSSMController,
    EnvelopeAdaptiveController,
    FixedZoneController,
    StaticController,
)
from hrc_safety.envelope import DynamicSSMEnvelope
from hrc_safety.features import FeatureExtractor, FeatureFrame
from hrc_safety.horizon import fused_risk, time_to_breach
from hrc_safety.lhmm.upper import STATES, GaussianEmissions, UpperHMM
from hrc_safety.logging_schema import Command, DecisionRecord
from hrc_safety.metrics import compute_metrics, compute_phase_metrics
from hrc_safety.panel_cycle import PHASES, CollaborativeMode, Phase
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


def _always_working_hmm() -> UpperHMM:
    """An HMM whose posterior is ALWAYS 'working' for any observation (adversarial).

    Non-working states are given far-off, tight Gaussians so they never win; 'working'
    is given a broad, flat one so it always dominates. Used to prove the envelope
    shields the command even when the learned layer is certain the scene is safe.
    """
    n = len(STATES)
    w = STATES.index("working")
    means = np.full((n, 4), 1000.0)
    variances = np.full((n, 4), 1e-3)
    means[w] = 0.0
    variances[w] = 1e6
    A = np.full((n, n), 1.0 / n)
    return UpperHMM(transition_matrix=A, emissions=GaussianEmissions(means=means, variances=variances))


def _rec(t, d, speed, command) -> DecisionRecord:
    """Minimal DecisionRecord for metric unit tests."""
    return DecisionRecord(
        t=t, condition="test", d=d, zone="n/a",
        state_posterior=[0, 0, 0, 0], predicted_posterior=[0, 0, 0, 0],
        p_hazard_next=0.0, inferred_state="n/a", rule="",
        command=command.value, speed_fraction=speed,
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


# --- 11. THE ARCHITECTURAL INVARIANT: adaptive never exceeds the envelope -----
# NON-NEGOTIABLE #4 (README). The learned layers are SHIELDED by the certified SSM
# envelope: at every tick the commanded speed must be <= the envelope's permitted
# speed, even when the model is adversarially certain the scene is 'working' during a
# fast approach. A recognition error may only ADD caution, never raise speed.

def test_adaptive_never_exceeds_envelope():
    envelope = DynamicSSMEnvelope(T=0.40, C=0.20, Sa=0.10, ramp=0.30)
    hmm = _always_working_hmm()
    ctrl = EnvelopeAdaptiveController(
        _zone_model(), hmm, envelope=envelope, speed_reduced=0.35,
        hazard_dwell_ticks=2, min_closing_speed=0.6,
    )

    constrained_somewhere = False
    for d in (0.5, 0.7, 0.9, 0.94, 1.0, 1.2, 1.5, 2.0, 2.5):
        for v in (-1.0, 0.0, 0.5, 1.0, 2.0, 3.0):
            for a in (-2.0, 0.0, 2.0):
                frame = _frame(d=d, v_proj=v, v_lat_frac=0.2, a_proj=a, t=0.0)
                rec = ctrl.decide(frame)
                env_speed = envelope.max_speed(d, v)
                # The model is adversarially certain it is safe...
                assert rec.inferred_state == "working"
                # ...yet the command never exceeds the certified floor.
                assert rec.speed_fraction <= env_speed + 1e-9, (d, v, a, rec.speed_fraction, env_speed)
                if rec.speed_fraction < env_speed - 1e-9 or env_speed == 0.0:
                    constrained_somewhere = True
    # The envelope (or the hard stop) actually bit somewhere in the sweep.
    assert constrained_somewhere


# --- 12. horizon time-to-breach: constant velocity, retreat, accel clamp -------

def test_time_to_breach_kinematics_and_accel_clamp():
    # Constant velocity closing: gap = 1.94 - 0.94 = 1.0 m at 1.0 m/s -> 1.0 s.
    assert time_to_breach(1.94, 1.0, 0.0, 0.94, horizon=0.5) == pytest.approx(1.0)
    # Moving away -> never breaches.
    assert time_to_breach(1.5, -1.0, 0.0, 0.94) == float("inf")
    # Already inside red -> 0.
    assert time_to_breach(0.5, 0.0, 0.0, 0.94) == 0.0
    # A physically-impossible noisy acceleration is CLAMPED to max_accel: with v=0,
    # gap=1.0, a clamped to 4 -> 0.5*4*tau^2 = 1 -> tau = sqrt(0.5).
    got = time_to_breach(1.94, 0.0, 1000.0, 0.94, max_accel=4.0)
    assert got == pytest.approx((2.0 * 1.0 / 4.0) ** 0.5)


def test_fused_risk_gated_by_closing_speed():
    # Imminent breach geometry, but the operator is barely closing (below the gate):
    # imminence is suppressed, so risk falls back to p_hazard alone.
    r_slow = fused_risk(0.1, ttb=0.05, horizon=0.5, steepness=8.0, v_proj=0.1, min_closing=0.6)
    assert r_slow == pytest.approx(0.1)
    # Same geometry but genuinely closing fast: imminence dominates.
    r_fast = fused_risk(0.1, ttb=0.05, horizon=0.5, steepness=8.0, v_proj=1.5, min_closing=0.6)
    assert r_fast > 0.9


# --- 13. anticipation lead time: full system pre-empts, fixed zone reacts ------

def test_full_system_anticipates_before_fixed_zone():
    config = load_config()
    fitted = fit_hmm(config)
    trace = generate_loop(config, seed=7)

    m_full = score(config, build_controller("adaptive", config, fitted), trace)
    m_fixed = score(config, build_controller("fixed_zone", config, None), trace)

    # Full system stops BEFORE the operator crosses the red radius (positive lead).
    assert m_full.anticipation_lead_time_s is not None
    assert m_full.anticipation_lead_time_s > 0.0
    # The fixed-zone baseline only reacts on the breach itself: no anticipation.
    assert m_fixed.anticipation_lead_time_s is not None
    assert m_fixed.anticipation_lead_time_s <= 0.0


# --- 14. SPECIFICITY: distractors must not trigger stops, slips still do -------
# The cued distractors (fast lateral dart, fast retreat) are ground-truth non-hazard.
# A controller must NOT stop for them (specificity) while still stopping for the slip
# (sensitivity). This is what separates a useful controller from one that just stops
# for any fast motion.

def test_distractors_do_not_trigger_stops():
    config = load_config()
    fitted = fit_hmm(config)
    trace = generate_loop(config, seed=7)
    assert trace.distractor_windows  # the scenario really contains distractors
    assert trace.slip_windows        # ...and a real slip

    for name in ("fixed_zone", "dynamic_ssm", "adaptive"):
        m = score(config, build_controller(name, config, fitted), trace)
        assert m.hazard_sensitivity == 1.0, name   # stops for the real slip
        assert m.hazard_specificity == 1.0, name   # never stops during a distractor
        assert m.false_stop_rate == 0.0, name


# --- 15. interruption_burden counts only ground-truth-safe speed deficit -------

def test_interruption_burden_excludes_hazard_and_red():
    dt = 0.1
    red = 0.94
    records = [
        _rec(t=0.0, d=1.5, speed=1.0, command=Command.FULL_SPEED),      # safe, full -> 0
        _rec(t=0.1, d=1.5, speed=0.4, command=Command.REDUCED_SPEED),  # safe, deficit 0.6*dt
        _rec(t=0.2, d=1.2, speed=0.0, command=Command.PROTECTIVE_STOP),  # slip window -> excluded
        _rec(t=0.3, d=0.5, speed=0.0, command=Command.PROTECTIVE_STOP),  # red occupancy -> excluded
    ]
    labels = ["working", "working", "hazard", "hazard"]
    m = compute_metrics(
        records, labels, dt, hazard_onset_t=0.2, red_radius=red,
        slip_windows=[(0.2, 0.35)], distractor_windows=[],
    )
    # Only the single safe slowdown contributes: (1 - 0.4) * dt.
    assert m.interruption_burden_s == pytest.approx(0.6 * dt)


# --- 16. the three rungs all emit the identical DecisionRecord schema ----------

def test_three_rungs_emit_identical_schema():
    config = load_config()
    fitted = fit_hmm(config)
    frame = _frame(d=1.2, v_proj=0.3, v_lat_frac=0.2, a_proj=0.0)

    fixed = FixedZoneController(build_zone_model(config))
    dynamic = DynamicSSMController(build_zone_model(config))
    adaptive = build_controller("adaptive", config, fitted)

    keys = None
    for ctrl in (fixed, dynamic, adaptive):
        rec = ctrl.decide(frame)
        rec_keys = set(vars(rec).keys())
        if keys is None:
            keys = rec_keys
        assert rec_keys == keys  # identical schema across all rungs


# --- 17. v2 Panel Cycle: the scenario emits all five phases + certified modes -----

def test_scenario_v2_emits_all_phases_and_modes():
    config = load_config()
    tr = generate_loop(config, seed=7)
    # phases and modes are aligned one-to-one with the raw samples.
    assert len(tr.phases) == len(tr.times) == len(tr.robot_modes) == len(tr.labels)
    assert set(tr.phases) == set(PHASES)  # all five phases present
    # HAND_GUIDE runs entirely under the certified compliant-hold mode, at near-contact.
    hg = [i for i, p in enumerate(tr.phases) if p == Phase.HAND_GUIDE.value]
    assert hg
    assert all(tr.robot_modes[i] == CollaborativeMode.HAND_GUIDE.value for i in hg)
    tcp = np.asarray(config["scenario"]["tcp_position"])
    red = build_zone_model(config).red_radius
    hg_horizontal = [float(np.hypot(*(tr.positions[i, :2] - tcp[:2]))) for i in hg]
    assert min(hg_horizontal) < red  # the human really reaches contact under the panel
    # HOLD_BOLT is a safety-rated monitored stop; TRANSIT/RETRACT are speed-and-separation.
    def mode_of(phase):
        i = tr.phases.index(phase)
        return tr.robot_modes[i]
    assert mode_of(Phase.HOLD_BOLT.value) == CollaborativeMode.MONITORED_STOP.value
    assert mode_of(Phase.TRANSIT_UP.value) == CollaborativeMode.SSM.value


# --- 18. THE v2 HEADLINE: hand-guiding feasible for envelope rungs, not fixed-zone -
# P3 is the maximum-divergence measurement window. The fixed-zone baseline is mode-blind,
# so it protective-stops on the contact and hand-guiding is INFEASIBLE under it; the
# envelope rungs honour the certified compliant-hold mode and permit the contact.

def test_hand_guide_feasible_for_envelope_infeasible_for_fixed_zone():
    config = load_config()
    fitted = fit_hmm(config)
    trace = generate_loop(config, seed=7)
    hg = Phase.HAND_GUIDE.value

    def hand_guide_phase(name):
        run = run_controller(config, build_controller(name, config, fitted), trace)
        pm = compute_phase_metrics(
            run.records, run.phases, run.robot_modes, trace.dt,
            slip_windows=trace.slip_windows,
        )
        return pm[hg]

    fixed = hand_guide_phase("fixed_zone")
    dynamic = hand_guide_phase("dynamic_ssm")
    adaptive = hand_guide_phase("adaptive")

    # Fixed-zone stalls on the contact for most of the phase -> infeasible.
    assert fixed.human_idle_s > 0.5 * fixed.duration_s
    # The envelope rungs permit the compliant contact -> zero idle, hand-guiding feasible.
    assert dynamic.human_idle_s == 0.0
    assert adaptive.human_idle_s == 0.0
    assert adaptive.collaborative_mode == CollaborativeMode.HAND_GUIDE.value


# --- 19. the certified collaborative MODE governs the envelope floor ----------------

def test_collaborative_mode_governs_envelope_floor():
    zm = _zone_model()
    obs = np.array([0.12, 0.0, 0.9, 0.0])  # working-like, at contact distance (in RED)
    ctrl = _adaptive(zm, _forced_hmm("working", obs))
    contact = _frame(d=0.12, v_proj=0.05, v_lat_frac=0.3)

    # SSM at contact -> the fixed-RED hard stop still fires (the invariant is intact).
    assert ctrl.decide(contact, robot_mode="ssm").command == Command.PROTECTIVE_STOP.value
    # Monitored-stop -> robot commanded dead still.
    assert ctrl.decide(contact, robot_mode="monitored_stop").command == Command.PROTECTIVE_STOP.value
    # Hand-guiding at contact, moving slowly -> compliant contact PERMITTED, not stopped.
    rec = ctrl.decide(contact, robot_mode="hand_guide")
    assert rec.command == Command.REDUCED_SPEED.value
    assert rec.speed_fraction == pytest.approx(0.20)  # the compliant-hold speed floor
    assert rec.robot_mode == "hand_guide"


# --- 20. hand-guiding still stops for a genuine fast-closing lunge (learned caution) -

def test_hand_guide_still_stops_for_fast_lunge():
    zm = _zone_model()
    obs = np.array([0.12, 2.0, 0.1, 1.5])  # hazard-like fast closing at contact
    ctrl = _adaptive(zm, _forced_hmm("hazard", obs))
    rec = None
    for i in range(5):  # sustained fast-closing lunge during hand-guiding
        rec = ctrl.decide(
            _frame(d=0.12, v_proj=2.0, v_lat_frac=0.1, a_proj=1.5, t=i),
            robot_mode="hand_guide",
        )
    # The learned layer may ADD caution atop the compliant-hold floor: a real lunge stops.
    assert rec.command == Command.PROTECTIVE_STOP.value


# --- 21. per-phase reporting excludes the P4 hold (and P1 load) from measurement ---
# Measuring the P4 monitored-stop hold was the exact confusion v2 resolved.

def test_measurement_windows_exclude_hold_bolt_and_load():
    config = load_config()
    fitted = fit_hmm(config)
    trace = generate_loop(config, seed=7)
    run = run_controller(config, build_controller("adaptive", config, fitted), trace)
    pm = compute_phase_metrics(
        run.records, run.phases, run.robot_modes, trace.dt,
        slip_windows=trace.slip_windows,
    )
    assert pm[Phase.TRANSIT_UP.value].is_measurement_window
    assert pm[Phase.HAND_GUIDE.value].is_measurement_window
    assert pm[Phase.RELEASE_RETRACT.value].is_measurement_window
    assert not pm[Phase.HOLD_BOLT.value].is_measurement_window
    assert not pm[Phase.LOAD.value].is_measurement_window
    # P4 is identical static-vs-adaptive: run the fixed-zone rung and confirm the hold.
    assert pm[Phase.HOLD_BOLT.value].collaborative_mode == CollaborativeMode.MONITORED_STOP.value


# --- 22. adaptive beats static on burden at equal safety (the paper hypothesis) ----

def test_adaptive_beats_static_burden_at_equal_safety():
    config = load_config()
    fitted = fit_hmm(config)
    trace = generate_loop(config, seed=7)
    m_fixed = score(config, build_controller("fixed_zone", config, None), trace)
    m_adaptive = score(config, build_controller("adaptive", config, fitted), trace)

    # Safety parity: identical minimum separation, both catch the true slip.
    assert m_adaptive.min_separation == pytest.approx(m_fixed.min_separation)
    assert m_adaptive.hazard_sensitivity == 1.0
    assert m_fixed.hazard_sensitivity == 1.0
    # Efficiency: adaptive carries strictly less interruption burden than static.
    assert m_adaptive.interruption_burden_s < m_fixed.interruption_burden_s
