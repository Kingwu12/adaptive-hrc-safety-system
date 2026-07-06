"""One-step state prediction (paper Eq.1).

Isolated in its own module because its output is AUDITED: the predicted next-step
posterior drives the adaptive controller's pre-emptive protective stop, so the
prediction step must be independently testable and traceable.

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
