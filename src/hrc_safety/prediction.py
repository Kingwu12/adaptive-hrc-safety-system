"""One-step state prediction (paper Eq.1).

SUPERSEDED AS THE ANTICIPATION MECHANISM (sem-2). See src/hrc_safety/horizon.py.
    At 60 Hz one step is 16 ms, and the upper HMM's transition matrix is sticky, so
    p_{t+1} = normalize(p_t @ A) is almost identical to p_t -- too small a lookahead
    to buy meaningful lead time before a red-zone breach. The anticipation claim now
    rests on KINEMATIC horizon prediction (constant-acceleration time-to-breach)
    fused with the state posterior, not on this one-step propagation.
    Eq.1 SURVIVES as a component: it is the transition-prediction half of the
    forward filter (UpperHMM.step). This module is retained for backward
    compatibility and for the ablation that removes horizon prediction.

Isolated in its own module because its output is AUDITED: the predicted next-step
posterior is traceable and independently testable.

    Eq.1:  p_{t+1} = normalize( p_t @ A )

where p_t is the current state posterior and A the (row-stochastic) transition matrix.
"""

from __future__ import annotations

import numpy as np

from .lhmm.upper import STATES, _INDEX


def predict_next(p: np.ndarray, A: np.ndarray) -> np.ndarray:
    """Paper Eq.1: propagate the posterior one step through A and renormalise."""
    p = np.asarray(p, dtype=float)
    A = np.asarray(A, dtype=float)
    nxt = p @ A
    s = nxt.sum()
    return nxt / s if s > 0 else np.full(len(p), 1.0 / len(p))


def hazard_probability(p_next: np.ndarray) -> float:
    """Probability mass on the 'hazard' state in a (predicted) posterior."""
    return float(np.asarray(p_next, dtype=float)[_INDEX["hazard"]])


__all__ = ["predict_next", "hazard_probability", "STATES"]
