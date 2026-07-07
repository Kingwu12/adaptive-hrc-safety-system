"""Dynamic Speed-and-Separation safety ENVELOPE -- the certified speed floor.

WHY THIS MODULE EXISTS (viva defence, in one line):
    "The smart part can only ADD caution, never remove it."

The sem-1 design let the adaptive controller reason its way to FULL speed inside
the yellow band (e.g. "operator is retreating -> no need to slow"). That makes the
learned model part of the SAFETY-CRITICAL path: a recognition error could raise the
commanded speed. Certifying a learned model to that standard is the hard problem in
the whole field. This module removes that burden.

The envelope is a STATE-BLIND, SPEED-AWARE function of geometry alone. It implements
the ISO/TS 15066 Speed-and-Separation Monitoring stop distance using the MEASURED
approach speed v_proj instead of the fixed worst-case human speed K:

    S(t) = max(0, v_proj(t)) * T + C + Sa

and maps the current gap (d - S) to the MAXIMUM permissible speed fraction:

    d <= S            -> 0.0            (must be stopped: too close for this speed)
    S < d < S + ramp  -> (d - S)/ramp  (linear scale-down as separation tightens)
    d >= S + ramp     -> 1.0           (full speed permitted)

This is a certified FLOOR: the runtime-assurance / shielding pattern. The learned
LHMM layer sits ON TOP and may only reduce the command below the envelope, never
raise it above -- so a recognition error can at worst make the robot too cautious,
which is safe. This is locked by test_adaptive_never_exceeds_envelope.

WHY v_proj, not K:  the fixed-K zone (K=1.6 m/s worst case) stops the robot for a
stationary worker standing 1.1 m away, because it assumes they might lunge at full
speed. The envelope reads the actual approach speed: a stationary worker (v_proj~=0)
gets S = C + Sa, so the robot may keep moving -- exactly the efficiency the standard
permits, WITHOUT any belief about intent. When the operator actually approaches at
the nominal K, S rises to K*T + C + Sa == the old fixed red radius. The envelope is
therefore never LESS safe than the fixed zone at the speed the zone assumed; it is
only less conservative when the person is demonstrably moving slower.

NOTE the envelope is NOT the absolute floor on its own: at v_proj~=0 its stop
distance (C + Sa) is well inside the certified fixed RED radius. The fixed-zone RED
hard-stop invariant is kept ON TOP of the envelope in the controllers, so a body
inside the certified red radius always stops regardless of measured speed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvelopeDecision:
    """Traceable result of one envelope evaluation."""

    stop_distance: float  # S(t) = max(0, v_proj)*T + C + Sa
    max_speed: float      # maximum permissible speed fraction in [0, 1]


class DynamicSSMEnvelope:
    """Speed-aware ISO/TS 15066 stop-distance envelope (the certified floor).

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
