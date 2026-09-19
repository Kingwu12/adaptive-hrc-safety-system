"""Prototype dynamic speed-and-separation envelope: a command bound.

The simplified threshold is S(t) = max(0, v_proj(t))*T + C + Sa.
For gap d-S, the requested speed limit is zero below the threshold, ramps
linearly over the configured band, then reaches one.

In SSM mode the adaptive controller caps its request by this envelope and also
applies the shared fixed-red override. That arithmetic relationship holds for
the same inputs and parameters; it does not establish physical safety or show
that the dynamic rule is as safe as a fixed-zone rule in an installed cell.

This is a standards-informed research model, not the complete protective
separation calculation or a certified safety function. Sensor uncertainty,
robot/human geometry, robot motion, reaction and stopping behaviour, and the
physical output chain require independent treatment and validation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvelopeDecision:
    """Traceable result of one envelope evaluation."""

    stop_distance: float  # S(t) = max(0, v_proj)*T + C + Sa
    max_speed: float      # maximum permissible speed fraction in [0, 1]


class DynamicSSMEnvelope:
    """Standards-informed prototype stop-distance envelope.

    T, C, Sa are the SAME quantities the ZoneModel uses (system reaction/stopping
    time, sensor intrusion distance, operator position uncertainty). They have ONE
    owner -- the `zones` config block -- and are passed in here, never re-declared.
    """

    def __init__(self, T: float, C: float, Sa: float, ramp: float) -> None:
        self.T = float(T)
        self.C = float(C)
        self.Sa = float(Sa)
        self.ramp = float(ramp)
        if self.ramp <= 0.0:
            raise ValueError("ramp must be positive (it is the speed-scaling band width)")

    def stop_distance(self, v_proj: float) -> float:
        """S(t) = max(0, v_proj)*T + C + Sa.

        Only the CLOSING component of velocity contributes: an operator moving away
        (v_proj < 0) is clamped to 0, so retreat never inflates the stop distance.
        """
        closing = max(0.0, float(v_proj))
        return closing * self.T + self.C + self.Sa

    def max_speed(self, d: float, v_proj: float) -> float:
        """Maximum permissible speed fraction in [0, 1] for gap d at approach v_proj."""
        return self.evaluate(d, v_proj).max_speed

    def evaluate(self, d: float, v_proj: float) -> EnvelopeDecision:
        """Full traceable evaluation: stop distance + permissible speed."""
        s = self.stop_distance(v_proj)
        d = float(d)
        if d <= s:
            frac = 0.0
        elif d >= s + self.ramp:
            frac = 1.0
        else:
            frac = (d - s) / self.ramp
        # Clamp defensively; the branches above already bound it, but a NaN d must
        # never escape as a permissive speed.
        frac = min(1.0, max(0.0, frac))
        return EnvelopeDecision(stop_distance=s, max_speed=frac)


def build_envelope(config: dict) -> DynamicSSMEnvelope:
    """Construct the envelope, reusing T, C, Sa from the zones block (SINGLE SOURCE)."""
    z = config["zones"]
    e = config["envelope"]
    return DynamicSSMEnvelope(T=z["T"], C=z["C"], Sa=z["Sa"], ramp=e["ramp"])
