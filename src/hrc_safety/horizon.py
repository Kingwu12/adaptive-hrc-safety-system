"""Horizon prediction -- "predict where they'll BE, not the next tick's label".

WHY THIS SUPERSEDES THE ONE-STEP p@A ANTICIPATION CLAIM (viva defence):
    At 60 Hz one step is 16 ms. The upper HMM's transition matrix is deliberately
    STICKY (high self-transition), so p_{t+1} = normalize(p_t @ A) is almost
    identical to p_t. Calling a 16 ms, barely-changed posterior "anticipation" is
    close to vacuous -- it cannot buy the robot meaningful lead time before a breach.
    Eq.1 survives as a COMPONENT of the model (it is how the filter propagates
    belief), but it is NOT the anticipation mechanism. `prediction.py` is kept for
    backward compatibility and is marked superseded there.

WHAT WE DO INSTEAD:
    Anticipation is a KINEMATIC question, not a labelling one. We extrapolate the
    operator's motion under constant acceleration over a real horizon (~0.5 s) and
    ask: do they cross the red radius within that horizon, and how soon?

        d(tau) = d - v_proj*tau - 0.5*a_proj*tau^2      (closing shrinks d)
        breach when d(tau) <= red_radius

    time_to_breach returns the smallest positive tau solving d(tau) == red_radius,
    or +inf if the operator does not breach within any positive horizon (e.g. they
    are moving away). This is speed-AND-acceleration aware, so a fast accelerating
    lunge is flagged seconds-scaled ahead of the boundary, not one 16 ms tick ahead.

TWO PHYSICAL GUARDS (why raw extrapolation is unusable here -- viva defence):
    Velocity and especially ACCELERATION are estimated by finite slopes over a jittery
    position sensor, so the raw a_proj routinely reads +-30 m/s^2 -- three times
    gravity, physically impossible for a human. Fed straight into 0.5*a*tau^2 that
    noise predicts an imminent breach almost every tick. We therefore:
      1. CLAMP the extrapolated acceleration to `max_accel` (a human-plausible bound,
         ~0.4 g). A larger apparent value is sensor noise, not motion, and must not
         drive a stop.
      2. GATE imminence on a minimum sustained CLOSING speed (`min_closing`). Genuine
         anticipation is about someone actually moving toward the hazard; a stationary
         worker 16 cm outside the boundary whose jitter momentarily reads as closing is
         not a breach. Below the gate, imminence is forced to 0.
    With both guards the predictor fires cleanly on the cued slip (sustained fast
    closing) and ignores working sway, lateral darts, and retreats.

FUSION RULE (documented plainly, used by the controller):
    We combine two independent hazard signals and take the MORE cautious of the two:

        imminence = sigmoid( steepness * (horizon_s - time_to_breach) )   in [0, 1]
                    (forced to 0 when closing speed < min_closing)
        risk      = max( p_hazard , imminence )

    - p_hazard is the state posterior's belief in the 'hazard' activity (what the
      operator is DOING -- a lunge posture, erratic motion).
    - imminence is pure geometry (where they will BE) -- it rises toward 1 as the
      predicted breach time drops below the horizon, and is ~0 when breach is far
      off or never (time_to_breach = inf -> imminence -> 0).
    max() means EITHER signal can trigger caution: a recognised hazard OR an
    imminent geometric breach. Neither can veto the other down -- caution only adds.
"""

from __future__ import annotations

import math

_INF = float("inf")


def time_to_breach(
    d: float,
    v_proj: float,
    a_proj: float,
    red_radius: float,
    horizon: float = 0.5,
    max_accel: float = 4.0,
) -> float:
    """Constant-acceleration time (s) until the operator crosses the red radius.

    Solves gap = v_proj*tau + 0.5*a_proj*tau^2 for the smallest tau > 0, where
    gap = d - red_radius is the current distance to the red boundary and the
    closing motion is (v_proj + a_proj*tau). The extrapolated acceleration is CLAMPED
    to +-max_accel (a human-plausible bound) so sensor-jitter accelerations cannot
    fabricate an imminent breach. Returns:
        0.0   if already at/inside the red radius,
        tau   the smallest positive breach time if it occurs,
        +inf  if the operator never reaches the boundary on a forward trajectory.

    `horizon` bounds the search: a breach predicted strictly beyond `horizon` is
    reported as its true tau (callers compare against horizon for imminence), but
    trajectories that turn around before breaching return +inf.
    """
    d = float(d)
    v = float(v_proj)
    a = max(-float(max_accel), min(float(max_accel), float(a_proj)))
    r = float(red_radius)

    gap = d - r
    if gap <= 0.0:
        return 0.0  # already breached

    # Solve 0.5*a*tau^2 + v*tau - gap = 0 for the smallest positive root.
    if abs(a) < 1e-9:
        # Constant velocity: breach only if closing (v > 0).
        if v <= 0.0:
            return _INF
        return gap / v

    disc = v * v + 2.0 * a * gap
    if disc < 0.0:
        # No real crossing: decelerating closer, turns around before the boundary.
        return _INF

    sqrt_disc = math.sqrt(disc)
    # Roots of (a/2) tau^2 + v tau - gap = 0.
    tau1 = (-v + sqrt_disc) / a
    tau2 = (-v - sqrt_disc) / a
    positive = [t for t in (tau1, tau2) if t > 1e-12]
    if not positive:
        return _INF
    return min(positive)


def breach_imminence(ttb: float, horizon: float, steepness: float) -> float:
    """Sigmoid mapping time-to-breach -> imminence in [0, 1].

    ~1 when a breach is predicted well within the horizon, 0.5 at exactly the
    horizon, ~0 when the breach is far off or never (ttb = +inf).
    """
    if math.isinf(ttb):
        return 0.0
    z = steepness * (horizon - ttb)
    # Numerically stable logistic.
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def fused_risk(
    p_hazard: float,
    ttb: float,
    horizon: float,
    steepness: float,
    v_proj: float = _INF,
    min_closing: float = 0.0,
) -> float:
    """risk = max(p_hazard, imminence(ttb)), with imminence gated by closing speed.

    When the operator's closing speed v_proj is below min_closing, the geometric
    imminence is forced to 0 (they are not meaningfully moving toward the hazard, so
    a small extrapolated time-to-breach is noise, not anticipation). The state-based
    p_hazard is never gated -- a recognised hazard posture still counts. See the
    module docstring for why this guard is necessary. Defaults leave the gate open.
    """
    if float(v_proj) < float(min_closing):
        imminence = 0.0
    else:
        imminence = breach_imminence(ttb, horizon, steepness)
    return max(float(p_hazard), imminence)


__all__ = ["time_to_breach", "breach_imminence", "fused_risk"]
