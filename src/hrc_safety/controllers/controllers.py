"""The two controllers under comparison.

StaticController   -- the baseline: zone -> command, nothing else.
AdaptiveController -- the paper's Table I: Recognise -> Predict -> Adapt.

SAFETY INVARIANT (locked by test_red_zone_always_stops_adaptive_even_if_model_says_working):
    A RED-zone breach forces a protective stop in BOTH conditions, checked FIRST,
    regardless of any model belief. No recognition/prediction result may weaken it.
    This branch is the permanent merge blocker -- never edit it to trust the model.
"""

from __future__ import annotations

import numpy as np

from ..features import FeatureFrame
from ..logging_schema import Command, DecisionRecord
from ..lhmm.upper import STATES, UpperHMM
from ..prediction import hazard_probability, predict_next
from ..zones import Zone, ZoneModel

def _zone_name(z: Zone) -> str:
    return z.name.lower()


class StaticController:
    """Distance-threshold baseline. Zone alone determines the command."""

    condition = "static"

    def __init__(self, zone_model: ZoneModel, speed_reduced: float = 0.35) -> None:
        self.zones = zone_model
        self.speed_reduced = float(speed_reduced)

    def decide(self, frame: FeatureFrame) -> DecisionRecord:
        zone = self.zones.update(frame.d)
        if zone == Zone.RED:
            command, speed, rule = (
                Command.PROTECTIVE_STOP,
                0.0,
                "RED zone breach -> protective stop (static baseline)",
            )
        elif zone == Zone.YELLOW:
            command, speed, rule = (
                Command.REDUCED_SPEED,
                self.speed_reduced,
                "YELLOW zone -> reduced speed (static baseline)",
            )
        else:
            command, speed, rule = (
                Command.FULL_SPEED,
                1.0,
                "GREEN zone -> full speed (static baseline)",
            )

        # The static baseline carries no model; report an empty/neutral posterior
        # so the shared schema stays consistent across conditions.
        neutral = [0.0, 0.0, 0.0, 0.0]
        return DecisionRecord(
            t=frame.t,
            condition=self.condition,
            d=frame.d,
            zone=_zone_name(zone),
            state_posterior=neutral,
            predicted_posterior=neutral,
            p_hazard_next=0.0,
            inferred_state="n/a",
            rule=rule,
            command=command.value,
            speed_fraction=speed,
        )


class AdaptiveController:
    """Recognise -> Predict -> Adapt controller implementing paper Table I."""

    condition = "adaptive"

    def __init__(
        self,
        zone_model: ZoneModel,
        upper_hmm: UpperHMM,
        speed_reduced: float = 0.35,
        hazard_prob_threshold: float = 0.35,
        hazard_dwell_ticks: int = 2,
        working_stability_ticks: int = 30,
    ) -> None:
        self.zones = zone_model
        self.hmm = upper_hmm
        self.speed_reduced = float(speed_reduced)
        self.hazard_prob_threshold = float(hazard_prob_threshold)
        self.hazard_dwell_ticks = int(hazard_dwell_ticks)
        self.working_stability_ticks = int(working_stability_ticks)
        self._hazard_streak = 0
        self._working_streak = 0

    def decide(self, frame: FeatureFrame) -> DecisionRecord:
        zone = self.zones.update(frame.d)

        # Recognise: streaming posterior from the observation.
        posterior = self.hmm.step(frame.as_vector())
        # Predict: one-step-ahead posterior (Eq.1).
        predicted = predict_next(posterior, self.hmm.A)
        p_haz = hazard_probability(predicted)
        inferred = STATES[int(np.argmax(posterior))]

        # Dwell debounce on sustained predicted hazard.
        if p_haz >= self.hazard_prob_threshold:
            self._hazard_streak += 1
        else:
            self._hazard_streak = 0

        # Track sustained working for stability accounting.
        if inferred == "working":
            self._working_streak += 1
        else:
            self._working_streak = 0

        command, speed, rule = self._decide_command(zone, inferred, p_haz)

        return DecisionRecord(
            t=frame.t,
            condition=self.condition,
            d=frame.d,
            zone=_zone_name(zone),
            state_posterior=[float(x) for x in posterior],
            predicted_posterior=[float(x) for x in predicted],
            p_hazard_next=float(p_haz),
            inferred_state=inferred,
            rule=rule,
            command=command.value,
            speed_fraction=speed,
        )

    def _decide_command(
        self, zone: Zone, inferred: str, p_haz: float
    ) -> tuple[Command, float, str]:
        # ---- SAFETY INVARIANT, FIRST AND ABSOLUTE ------------------------
        # A red-zone breach stops the robot no matter what the model believes.
        if zone == Zone.RED:
            return (
                Command.PROTECTIVE_STOP,
                0.0,
                "SAFETY INVARIANT: RED zone breach -> protective stop "
                "(overrides all model belief)",
            )

        # ---- Pre-emptive stop on sustained predicted hazard --------------
        if self._hazard_streak >= self.hazard_dwell_ticks:
            return (
                Command.PROTECTIVE_STOP,
                0.0,
                f"Predicted hazard P={p_haz:.2f} sustained "
                f">= {self.hazard_dwell_ticks} ticks -> pre-emptive protective stop",
            )

        # ---- Yellow-zone adaptive behaviour (Table I) --------------------
        if zone == Zone.YELLOW:
            if inferred == "retreating":
                return (
                    Command.FULL_SPEED,
                    1.0,
                    "YELLOW + retreating -> FULL speed (efficiency win: "
                    "operator is leaving, no need to slow)",
                )
            if inferred == "working":
                return (
                    Command.REDUCED_SPEED,
                    self.speed_reduced,
                    "YELLOW + working -> reduced speed (avoid stop; operator "
                    "stationary at the panel)",
                )
            # approaching or hazard-but-not-sustained -> conservative reduced speed.
            return (
                Command.REDUCED_SPEED,
                self.speed_reduced,
                f"YELLOW + {inferred} -> reduced speed (conservative)",
            )

        # ---- Green zone --------------------------------------------------
        return (
            Command.FULL_SPEED,
            1.0,
            "GREEN zone -> full speed",
        )
