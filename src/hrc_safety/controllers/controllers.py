"""The controllers under comparison -- now a THREE-RUNG ladder.

    FixedZoneController      -- rung 1: deployed practice. A fixed distance threshold
                                (K worst-case). Zone alone -> command. No speed
                                awareness, no state, no prediction. (== StaticController.)
    DynamicSSMController      -- rung 2: the STANDARDS rung. The ISO/TS 15066 dynamic
                                speed-and-separation ENVELOPE using the MEASURED
                                approach speed, and nothing else. No learned model.
    EnvelopeAdaptiveController -- rung 3: the FULL system. The envelope as a certified
                                floor, with the learned LHMM state layer and kinematic
                                horizon prediction layered ON TOP -- able only to ADD
                                caution below the envelope, never raise the command
                                above it.

ARCHITECTURAL INVARIANT (locked by test_adaptive_never_exceeds_envelope):
    commanded speed <= envelope-permitted speed, EVERY tick. The learned layers are
    shielded by the envelope: a recognition or prediction error can only make the
    robot MORE cautious, never faster. This is the runtime-assurance pattern and it
    is what lets us layer a non-certified learned model onto a safety-critical loop.

SAFETY INVARIANT (locked by test_red_zone_always_stops_adaptive_even_if_model_says_working):
    A fixed-RED-zone breach forces a protective stop, checked FIRST, regardless of any
    model belief OR the (speed-aware, possibly-permissive) envelope. The fixed red
    radius remains the absolute certified floor beneath the dynamic envelope.
"""

from __future__ import annotations

import numpy as np

from ..envelope import DynamicSSMEnvelope
from ..features import FeatureFrame
from ..horizon import fused_risk, time_to_breach
from ..logging_schema import Command, DecisionRecord
from ..lhmm.upper import STATES, UpperHMM
from ..prediction import hazard_probability, predict_next
from ..zones import Zone, ZoneModel

_NEUTRAL = [0.0, 0.0, 0.0, 0.0]


def _zone_name(z: Zone) -> str:
    return z.name.lower()


def _speed_to_command(speed: float) -> Command:
    """Map a continuous permissible-speed fraction to a discrete robot command."""
    if speed <= 0.0:
        return Command.PROTECTIVE_STOP
    if speed >= 1.0:
        return Command.FULL_SPEED
    return Command.REDUCED_SPEED


class FixedZoneController:
    """Rung 1 -- deployed-practice baseline. Fixed distance threshold; zone -> command.

    This is the currently-deployed pattern in most collaborative cells: a single
    worst-case protective distance (K = fixed human speed) drawn once, no awareness
    of how fast the operator is actually moving or what they are doing.
    """

    def __init__(
        self,
        zone_model: ZoneModel,
        speed_reduced: float = 0.35,
        condition: str = "static",
    ) -> None:
        self.zones = zone_model
        self.speed_reduced = float(speed_reduced)
        self.condition = condition

    def decide(self, frame: FeatureFrame) -> DecisionRecord:
        zone = self.zones.update(frame.d)
        if zone == Zone.RED:
            command, speed, rule = (
                Command.PROTECTIVE_STOP,
                0.0,
                "RED zone breach -> protective stop (fixed-zone baseline)",
            )
        elif zone == Zone.YELLOW:
            command, speed, rule = (
                Command.REDUCED_SPEED,
                self.speed_reduced,
                "YELLOW zone -> reduced speed (fixed-zone baseline)",
            )
        else:
            command, speed, rule = (
                Command.FULL_SPEED,
                1.0,
                "GREEN zone -> full speed (fixed-zone baseline)",
            )

        # The fixed-zone baseline carries no model; report a neutral posterior so the
        # shared schema stays consistent across conditions.
        return DecisionRecord(
            t=frame.t,
            condition=self.condition,
            d=frame.d,
            zone=_zone_name(zone),
            state_posterior=_NEUTRAL,
            predicted_posterior=_NEUTRAL,
            p_hazard_next=0.0,
            inferred_state="n/a",
            rule=rule,
            command=command.value,
            speed_fraction=speed,
        )


# Backward-compatible name: the original class was StaticController.
StaticController = FixedZoneController


class EnvelopeAdaptiveController:
    """Rung 3 -- full Recognise -> Predict -> Adapt, SHIELDED by the SSM envelope.

    The envelope is the certified FLOOR (max permissible speed from geometry + measured
    approach speed). The learned LHMM state layer and the kinematic horizon predictor
    sit on top and may only REDUCE the command below the envelope:

        final speed = min( envelope_max_speed , lhmm_caution_cap )

    with a fixed-RED hard stop and a sustained-risk pre-emptive stop above both.

    The `use_state_layer` and `use_horizon` flags exist for the REPLAY ABLATION:
      * use_horizon=False   -> "full minus prediction": falls back to the superseded
                               one-step p@A hazard instead of horizon time-to-breach.
      * use_state_layer=False -> "full minus state": envelope + hard stop only (this is
                               exactly rung 2, DynamicSSMController).
    """

    def __init__(
        self,
        zone_model: ZoneModel,
        upper_hmm: UpperHMM | None = None,
        envelope: DynamicSSMEnvelope | None = None,
        speed_reduced: float = 0.35,
        hazard_prob_threshold: float = 0.35,
        hazard_dwell_ticks: int = 2,
        working_stability_ticks: int = 30,
        horizon_s: float = 0.5,
        imminence_steepness: float = 8.0,
        risk_threshold: float | None = None,
        max_human_accel: float = 4.0,
        min_closing_speed: float = 0.6,
        ramp: float = 0.30,
        use_state_layer: bool = True,
        use_horizon: bool = True,
        condition: str = "adaptive",
    ) -> None:
        self.zones = zone_model
        self.hmm = upper_hmm
        # If no envelope is passed, derive it from the zone model's T, C, Sa so the
        # SSM parameters keep their SINGLE owner (the zones config block).
        self.envelope = envelope or DynamicSSMEnvelope(
            T=zone_model.T, C=zone_model.C, Sa=zone_model.Sa, ramp=ramp
        )
        self.speed_reduced = float(speed_reduced)
        self.hazard_prob_threshold = float(hazard_prob_threshold)
        self.hazard_dwell_ticks = int(hazard_dwell_ticks)
        self.working_stability_ticks = int(working_stability_ticks)
        self.horizon_s = float(horizon_s)
        self.imminence_steepness = float(imminence_steepness)
        self.max_human_accel = float(max_human_accel)
        self.min_closing_speed = float(min_closing_speed)
        self.risk_threshold = (
            float(risk_threshold) if risk_threshold is not None else float(hazard_prob_threshold)
        )
        self.use_state_layer = bool(use_state_layer)
        self.use_horizon = bool(use_horizon)
        self.condition = condition
        self._hazard_streak = 0
        self._working_streak = 0

    def decide(self, frame: FeatureFrame) -> DecisionRecord:
        zone = self.zones.update(frame.d)

        # ---- certified floor: envelope from geometry + measured approach speed ----
        env = self.envelope.evaluate(frame.d, frame.v_proj)

        # ---- Recognise: streaming state posterior (state layer) ------------------
        if self.use_state_layer and self.hmm is not None:
            posterior = self.hmm.step(frame.as_vector())
            inferred = STATES[int(np.argmax(posterior))]
            posterior_list = [float(x) for x in posterior]
            p_haz = hazard_probability(posterior)
        else:
            posterior = None
            inferred = "n/a"
            posterior_list = _NEUTRAL
            p_haz = 0.0

        # ---- Predict: kinematic horizon (or superseded one-step for the ablation) -
        ttb = time_to_breach(
            frame.d, frame.v_proj, frame.a_proj, self.zones.red_radius,
            self.horizon_s, self.max_human_accel,
        )
        if self.use_horizon:
            risk = fused_risk(
                p_haz, ttb, self.horizon_s, self.imminence_steepness,
                v_proj=frame.v_proj, min_closing=self.min_closing_speed,
            )
            predicted_list = posterior_list  # horizon does not produce a posterior
        elif posterior is not None:
            # Ablation: fall back to one-step p@A prediction (paper Eq.1).
            predicted = predict_next(posterior, self.hmm.A)
            risk = hazard_probability(predicted)
            predicted_list = [float(x) for x in predicted]
        else:
            risk = 0.0
            predicted_list = _NEUTRAL

        # Dwell debounce on sustained risk.
        if risk >= self.risk_threshold:
            self._hazard_streak += 1
        else:
            self._hazard_streak = 0
        if inferred == "working":
            self._working_streak += 1
        else:
            self._working_streak = 0

        command, speed, rule = self._decide_command(zone, env.max_speed, inferred, risk)

        ttb_out = None if ttb == float("inf") else float(ttb)
        return DecisionRecord(
            t=frame.t,
            condition=self.condition,
            d=frame.d,
            zone=_zone_name(zone),
            state_posterior=posterior_list,
            predicted_posterior=predicted_list,
            p_hazard_next=float(p_haz),
            inferred_state=inferred,
            rule=rule,
            command=command.value,
            speed_fraction=speed,
            envelope_max_speed=float(env.max_speed),
            risk=float(risk),
            time_to_breach_s=ttb_out,
        )

    def _decide_command(
        self, zone: Zone, envelope_max: float, inferred: str, risk: float
    ) -> tuple[Command, float, str]:
        # ---- SAFETY INVARIANT, FIRST AND ABSOLUTE ------------------------
        # A fixed-RED breach stops the robot no matter what the model believes and
        # no matter how permissive the speed-aware envelope is. The fixed red radius
        # is the certified floor beneath the dynamic envelope.
        if zone == Zone.RED:
            return (
                Command.PROTECTIVE_STOP,
                0.0,
                "SAFETY INVARIANT: RED zone breach -> protective stop "
                "(overrides envelope and all model belief)",
            )

        # ---- Pre-emptive stop on sustained risk (horizon breach OR hazard) -------
        if self._hazard_streak >= self.hazard_dwell_ticks:
            return (
                Command.PROTECTIVE_STOP,
                0.0,
                f"Fused risk={risk:.2f} sustained >= {self.hazard_dwell_ticks} ticks "
                "-> pre-emptive protective stop (horizon + state)",
            )

        # ---- Learned caution cap: the state layer may only REDUCE below envelope --
        cap = 1.0
        cap_reason = "no state caution"
        if self.use_state_layer and zone == Zone.YELLOW:
            if inferred == "retreating":
                cap, cap_reason = 1.0, "retreating -> no extra caution (envelope governs)"
            elif inferred in ("working", "approaching", "hazard"):
                cap = self.speed_reduced
                cap_reason = f"{inferred} in yellow -> cap at reduced speed"

        # ---- final = min(envelope floor, learned caution cap) --------------------
        speed = min(float(envelope_max), float(cap))
        command = _speed_to_command(speed)
        rule = (
            f"final speed=min(envelope={envelope_max:.2f}, cap={cap:.2f}) "
            f"[{cap_reason}] -> {command.value}"
        )
        return command, speed, rule


# Backward-compatible name: the original class was AdaptiveController.
AdaptiveController = EnvelopeAdaptiveController


class DynamicSSMController(EnvelopeAdaptiveController):
    """Rung 2 -- the STANDARDS rung. The dynamic SSM envelope alone (no learned model).

    This is ISO/TS 15066 done properly with the measured approach speed: it is what a
    conscientious integrator could deploy WITHOUT any machine learning. Isolating it as
    its own rung lets the ablation attribute gains to speed-awareness (rung1 -> rung2)
    separately from state/prediction reasoning (rung2 -> rung3).
    """

    def __init__(
        self,
        zone_model: ZoneModel,
        envelope: DynamicSSMEnvelope | None = None,
        speed_reduced: float = 0.35,
        ramp: float = 0.30,
        condition: str = "dynamic_ssm",
    ) -> None:
        super().__init__(
            zone_model,
            upper_hmm=None,
            envelope=envelope,
            speed_reduced=speed_reduced,
            ramp=ramp,
            use_state_layer=False,
            use_horizon=False,
            condition=condition,
        )
