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

COLLABORATIVE MODE (v2 -- the certified floor is mode-aware, the learned layer is not):
    Each tick carries the robot's certified collaborative mode (a robot-reported FACT,
    never a learned inference): SSM / hand-guiding / monitored-stop. The certified floor
    keys off it:
      * MONITORED_STOP  -- robot commanded dead still (P1 load, P4 bolt).
      * HAND_GUIDE      -- compliant hold: contact is permitted by design at the certified
                           compliant-hold speed, so the fixed-RED breach does NOT stop
                           (P3). The learned layer may still ADD caution on top -- a
                           sustained genuine hazard still stops -- but never removes it.
      * SSM             -- the dynamic envelope + fixed-RED hard stop govern, exactly as
                           before (P2 transit, P5 retract).
    `FixedZoneController` is MODE-BLIND (deployed practice predates mode integration): it
    only sees distance, so at contact range (P3) it protective-stops -- hand-guiding is
    infeasible under it. That mode-blindness is the P3 static-vs-adaptive divergence, and
    it is why the certified compliant-hold recognition lives in the FLOOR (shared by the
    envelope rungs), never in the learned layer.
"""

from __future__ import annotations

import numpy as np

from ..envelope import DynamicSSMEnvelope
from ..features import FeatureFrame
from ..horizon import fused_risk, time_to_breach
from ..logging_schema import Command, DecisionRecord
from ..lhmm.upper import STATES, UpperHMM
from ..panel_cycle import CollaborativeMode
from ..prediction import hazard_probability, predict_next
from ..zones import Zone, ZoneModel

_SSM = CollaborativeMode.SSM.value
_HAND_GUIDE = CollaborativeMode.HAND_GUIDE.value
_MONITORED_STOP = CollaborativeMode.MONITORED_STOP.value

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

    def decide(self, frame: FeatureFrame, robot_mode: str = _SSM) -> DecisionRecord:
        # MODE-BLIND by design: the deployed fixed-zone baseline sees only distance. The
        # certified mode is recorded for traceability but never changes the decision --
        # which is exactly why hand-guiding (contact range) is infeasible under it.
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
            robot_mode=robot_mode,
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
        compliant_hold_speed: float = 0.20,
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
        self.compliant_hold_speed = float(compliant_hold_speed)
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

    def decide(self, frame: FeatureFrame, robot_mode: str = _SSM) -> DecisionRecord:
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

        # A genuine hazard is a FAST CLOSING motion. During certified hand-guiding this is
        # the only thing that should still stop the robot: slow, deliberate contact (the
        # normal case) must not, or hand-guiding is not feasible. The sticky state
        # posterior naturally lights up near the robot, so it alone cannot gate the stop.
        closing_fast = frame.v_proj >= self.min_closing_speed

        command, speed, rule = self._decide_command(
            zone, env.max_speed, inferred, risk, robot_mode, closing_fast
        )

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
            robot_mode=robot_mode,
        )

    def _decide_command(
        self, zone: Zone, envelope_max: float, inferred: str, risk: float,
        robot_mode: str, closing_fast: bool,
    ) -> tuple[Command, float, str]:
        # ---- CERTIFIED COLLABORATIVE MODE governs the floor first (certified fact) ----
        # The robot-reported mode is not a learned belief; it selects which certified
        # floor applies. The learned layer below may only ADD caution, never remove it.
        if robot_mode == _MONITORED_STOP:
            # Safety-rated monitored stop (P1 load, P4 bolt): robot commanded dead still.
            return (
                Command.PROTECTIVE_STOP,
                0.0,
                "certified MONITORED-STOP mode -> robot held dead still (SMS)",
            )
        if robot_mode == _HAND_GUIDE:
            # Hand-guiding (P3): the robot holds the panel compliantly and the human
            # nudges it -- contact is permitted BY DESIGN, so the fixed-RED breach does
            # NOT stop. The learned layer may still ADD caution: a sustained AND genuinely
            # fast-closing hazard (a real lunge, not a slow deliberate touch) still forces a
            # pre-emptive stop. The closing-speed gate is what keeps ordinary hand-guiding
            # feasible while preserving the "learned layer only adds caution" guarantee.
            if closing_fast and self._hazard_streak >= self.hazard_dwell_ticks:
                return (
                    Command.PROTECTIVE_STOP,
                    0.0,
                    f"sustained fast-closing hazard (risk={risk:.2f}) during hand-guiding "
                    "-> stop (learned layer adds caution atop the compliant-hold floor)",
                )
            return (
                Command.REDUCED_SPEED,
                float(self.compliant_hold_speed),
                "certified HAND-GUIDING mode -> compliant contact permitted at "
                f"compliant-hold speed {self.compliant_hold_speed:.2f}",
            )

        # ---- SSM mode (P2 transit, P5 retract): the dynamic envelope + hard stop ----
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
        compliant_hold_speed: float = 0.20,
        ramp: float = 0.30,
        condition: str = "dynamic_ssm",
    ) -> None:
        super().__init__(
            zone_model,
            upper_hmm=None,
            envelope=envelope,
            speed_reduced=speed_reduced,
            compliant_hold_speed=compliant_hold_speed,
            ramp=ramp,
            use_state_layer=False,
            use_horizon=False,
            condition=condition,
        )
