"""Lower layer of the Layered HMM: coarse motion mode (stationary vs walking).

A fast, 2-state sub-model that feeds the upper layer. Its emission is a sigmoid
speed likelihood centred on ~0.15 m/s (below = stationary, above = walking), and
its transitions are STICKY so a single jittery sample does not flip the mode.
"""

from __future__ import annotations

import numpy as np

MODES: tuple[str, ...] = ("stationary", "walking")

# Sticky 2x2 transition matrix: rows = from, cols = to (stationary, walking).
_STICKY = np.array([[0.95, 0.05], [0.05, 0.95]], dtype=float)


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + np.exp(-z))


class LowerHMM:
    """Two-state stationary/walking filter with sigmoid speed likelihood."""

    def __init__(
        self,
        speed_threshold: float = 0.15,
        steepness: float = 25.0,
        transitions: np.ndarray | None = None,
    ) -> None:
        self.speed_threshold = float(speed_threshold)
        self.steepness = float(steepness)
        self.A = _STICKY.copy() if transitions is None else np.asarray(
            transitions, dtype=float
        )
        self._belief = np.array([0.5, 0.5], dtype=float)

    @property
    def belief(self) -> np.ndarray:
        return self._belief.copy()

    def reset(self) -> None:
        self._belief = np.array([0.5, 0.5], dtype=float)

    def _emission(self, speed: float) -> np.ndarray:
        """P(speed | mode). Walking likelihood rises through speed_threshold."""
        p_walk = _sigmoid(self.steepness * (speed - self.speed_threshold))
        return np.array([1.0 - p_walk, p_walk], dtype=float)

    def step(self, speed: float) -> np.ndarray:
        """One forward-filter step; returns posterior over (stationary, walking)."""
        predicted = self._belief @ self.A
        post = predicted * self._emission(float(speed))
        s = post.sum()
        self._belief = post / s if s > 0 else np.array([0.5, 0.5])
        return self._belief.copy()

    def p_walking(self, speed: float) -> float:
        return float(self.step(speed)[1])
