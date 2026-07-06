"""Upper layer of the Layered HMM: operator-state recognition.

States: approaching / working / retreating / hazard.
Emissions: diagonal-Gaussian over the feature vector [d, v_proj, v_lat_frac, a_proj].

Three entry points, matching the paper's reporting discipline:
  * step(x)   -- streaming forward-filter update; returns the online posterior the
                 controller consumes tick-by-tick.
  * viterbi(X)-- offline most-likely path over a whole trace, for validation
                 against labelled ground truth.
  * fit_transitions(...) / fit_emissions(...) -- learn A and the emissions from
                 labelled loops. THESE produce the REPORTED model. Hand-set values
                 are cold-start priors only; reporting them would be circular
                 validation (grading the model on the numbers we typed in).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STATES: tuple[str, ...] = ("approaching", "working", "retreating", "hazard")
_INDEX = {s: i for i, s in enumerate(STATES)}

# Feature vector order (must match FeatureFrame.as_vector):
#   [ d, v_proj, v_lat_frac, a_proj ]
_N_FEATURES = 4


@dataclass
class GaussianEmissions:
    """Diagonal-Gaussian emission model, one (mean, var) per state."""

    means: np.ndarray  # (n_states, n_features)
    variances: np.ndarray  # (n_states, n_features), strictly positive

    def log_likelihood(self, x: np.ndarray) -> np.ndarray:
        """Per-state log p(x | state) for one observation vector x."""
        diff = x[None, :] - self.means
        # log N = -0.5 * [ sum log(2*pi*var) + sum diff^2/var ]
        log_norm = np.sum(np.log(2.0 * np.pi * self.variances), axis=1)
        quad = np.sum((diff * diff) / self.variances, axis=1)
        return -0.5 * (log_norm + quad)


def default_emissions() -> GaussianEmissions:
    """Physics-motivated cold-start emissions (COLD START ONLY -- not reported).

    Rough priors so the filter behaves sanely before pilot data exists:
      approaching -- mid distance, closing (v_proj>0), low lateral fraction, +accel.
      working     -- near work_radius, ~stationary net, high lateral (sway), ~0 accel.
      retreating  -- mid distance, opening (v_proj<0), low lateral fraction.
      hazard      -- small distance, fast closing, low lateral, strong +accel (lunge).
    Columns: [ d, v_proj, v_lat_frac, a_proj ].
    """
    means = np.array(
        [
            [1.30, 0.60, 0.15, 0.30],   # approaching
            [1.10, 0.00, 0.80, 0.00],   # working
            [1.30, -0.60, 0.15, -0.20], # retreating
            [0.70, 1.80, 0.10, 1.50],   # hazard
        ],
        dtype=float,
    )
    variances = np.array(
        [
            [0.20, 0.25, 0.10, 0.30],
            [0.15, 0.10, 0.15, 0.15],
            [0.20, 0.25, 0.10, 0.30],
            [0.20, 0.60, 0.10, 0.80],
        ],
        dtype=float,
    )
    return GaussianEmissions(means=means, variances=variances)


class UpperHMM:
    """Interpretable 4-state HMM over the operator's activity."""

    def __init__(
        self,
        transition_matrix: np.ndarray,
        emissions: GaussianEmissions | None = None,
        start_prob: np.ndarray | None = None,
    ) -> None:
        A = np.asarray(transition_matrix, dtype=float)
        if A.shape != (len(STATES), len(STATES)):
            raise ValueError(f"transition_matrix must be {len(STATES)}x{len(STATES)}")
        self.A = A
        self.emissions = emissions if emissions is not None else default_emissions()
        if start_prob is None:
            start_prob = np.full(len(STATES), 1.0 / len(STATES))
        self._belief = np.asarray(start_prob, dtype=float)
        self._start = self._belief.copy()

    # ---- streaming (online) ----------------------------------------------

    @property
    def belief(self) -> np.ndarray:
        return self._belief.copy()

    def reset(self) -> None:
        self._belief = self._start.copy()

    def step(self, x: np.ndarray) -> np.ndarray:
        """One forward-filter step: predict through A, weight by emission, normalise.

        Returns the posterior over states AFTER incorporating observation x.
        This posterior is what the online controller consumes.
        """
        x = np.asarray(x, dtype=float)
        predicted = self._belief @ self.A  # transition prediction
        log_em = self.emissions.log_likelihood(x)
        # Work in log space for the emission weighting, then renormalise stably.
        log_post = np.log(predicted + 1e-300) + log_em
        log_post -= log_post.max()
        post = np.exp(log_post)
        s = post.sum()
        post = post / s if s > 0 else np.full(len(STATES), 1.0 / len(STATES))
        self._belief = post
        return post.copy()

    # ---- offline (validation) --------------------------------------------

    def viterbi(self, X: np.ndarray) -> list[str]:
        """Most-likely state path over an observation sequence (offline validation)."""
        X = np.asarray(X, dtype=float)
        if X.ndim != 2:
            raise ValueError("X must be (T, n_features)")
        T = X.shape[0]
        n = len(STATES)
        log_A = np.log(self.A + 1e-300)
        log_start = np.log(self._start + 1e-300)

        delta = np.empty((T, n))
        psi = np.zeros((T, n), dtype=int)

        delta[0] = log_start + self.emissions.log_likelihood(X[0])
        for t in range(1, T):
            em = self.emissions.log_likelihood(X[t])
            for j in range(n):
                scores = delta[t - 1] + log_A[:, j]
                psi[t, j] = int(np.argmax(scores))
                delta[t, j] = scores[psi[t, j]] + em[j]

        path = [0] * T
        path[-1] = int(np.argmax(delta[-1]))
        for t in range(T - 2, -1, -1):
            path[t] = psi[t + 1, path[t + 1]]
        return [STATES[i] for i in path]

    # ---- fitting (produces the REPORTED model) ---------------------------

    @classmethod
    def fit_transitions(
        cls, label_sequences, laplace: float = 1.0
    ) -> np.ndarray:
        """Estimate the transition matrix A from labelled state sequences.

        Laplace-smoothed transition counts (alpha default 1.0). Each row is
        renormalised to sum to 1. This is the REPORTED A.
        """
        n = len(STATES)
        counts = np.full((n, n), float(laplace))
        for seq in label_sequences:
            idx = [_INDEX[s] for s in seq]
            for a, b in zip(idx[:-1], idx[1:]):
                counts[a, b] += 1.0
        A = counts / counts.sum(axis=1, keepdims=True)
        return A

    @staticmethod
    def fit_emissions(
        X, labels, var_floor: float = 1e-3
    ) -> GaussianEmissions:
        """Maximum-likelihood diagonal-Gaussian emissions from labelled observations.

        X: (T, n_features) observations; labels: length-T state names.
        Variances are floored to var_floor for numerical stability. REPORTED.
        """
        X = np.asarray(X, dtype=float)
        n = len(STATES)
        means = np.zeros((n, _N_FEATURES))
        variances = np.full((n, _N_FEATURES), var_floor)
        for i, state in enumerate(STATES):
            mask = np.array([lab == state for lab in labels], dtype=bool)
            if not mask.any():
                # No examples for this state: fall back to the cold-start prior.
                prior = default_emissions()
                means[i] = prior.means[i]
                variances[i] = prior.variances[i]
                continue
            rows = X[mask]
            means[i] = rows.mean(axis=0)
            variances[i] = np.maximum(rows.var(axis=0), var_floor)
        return GaussianEmissions(means=means, variances=variances)
