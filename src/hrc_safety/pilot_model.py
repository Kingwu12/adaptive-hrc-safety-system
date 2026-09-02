"""Persistence for a pilot-fitted upper HMM.

The JSON artifact is deliberately small and contains fitted parameters plus
validation metadata, never raw participant frames.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .lhmm.upper import (STATES, GaussianEmissions, GaussianMixtureEmissions,
                         UpperHMM)

MODEL_SCHEMA_VERSION = 3
FEATURE_ORDER = ("d", "v_proj", "speed", "heading_alignment")


def model_payload(hmm: UpperHMM, **metadata) -> dict:
    """Return a JSON-serialisable representation of a fitted upper HMM."""
    if isinstance(hmm.emissions, GaussianMixtureEmissions):
        emissions = {
            "kind": "gaussian_mixture",
            "weights": hmm.emissions.weights.tolist(),
            "means": hmm.emissions.means.tolist(),
            "variances": hmm.emissions.variances.tolist(),
        }
    else:
        emissions = {
            "kind": "gaussian",
            "means": hmm.emissions.means.tolist(),
            "variances": hmm.emissions.variances.tolist(),
        }
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "states": list(STATES),
        "feature_order": list(FEATURE_ORDER),
        "transition_matrix": hmm.A.tolist(),
        "emissions": emissions,
        **metadata,
    }


def save_upper_hmm(path: str | Path, hmm: UpperHMM, **metadata) -> Path:
    """Write a fitted upper HMM atomically enough for the local lab workflow."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(model_payload(hmm, **metadata), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_upper_hmm(path: str | Path) -> UpperHMM:
    """Load and validate a fitted upper HMM JSON artifact."""
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != MODEL_SCHEMA_VERSION:
        raise ValueError(f"Unsupported pilot-model schema in {source}")
    if tuple(payload.get("states", ())) != STATES:
        raise ValueError(f"State order mismatch in {source}")
    if tuple(payload.get("feature_order", ())) != FEATURE_ORDER:
        raise ValueError(f"Feature order mismatch in {source}")

    A = np.asarray(payload["transition_matrix"], dtype=float)
    emissions_payload = payload["emissions"]
    means = np.asarray(emissions_payload["means"], dtype=float)
    variances = np.asarray(emissions_payload["variances"], dtype=float)
    if A.shape != (len(STATES), len(STATES)):
        raise ValueError(f"Invalid transition matrix shape in {source}: {A.shape}")
    if not np.isfinite(A).all() or not np.isfinite(means).all():
        raise ValueError(f"Non-finite model parameter in {source}")
    if not np.isfinite(variances).all() or np.any(variances <= 0):
        raise ValueError(f"Invalid emission variance in {source}")
    if not np.allclose(A.sum(axis=1), 1.0):
        raise ValueError(f"Transition rows do not sum to one in {source}")

    kind = emissions_payload.get("kind")
    if kind == "gaussian":
        if means.shape != (len(STATES), len(FEATURE_ORDER)) or variances.shape != means.shape:
            raise ValueError(f"Invalid Gaussian emission shape in {source}")
        emissions = GaussianEmissions(means=means, variances=variances)
    elif kind == "gaussian_mixture":
        weights = np.asarray(emissions_payload.get("weights"), dtype=float)
        expected_prefix = (len(STATES),)
        if (means.ndim != 3 or means.shape[:1] != expected_prefix
                or means.shape[2] != len(FEATURE_ORDER)
                or variances.shape != means.shape
                or weights.shape != means.shape[:2]):
            raise ValueError(f"Invalid mixture emission shape in {source}")
        if (not np.isfinite(weights).all() or np.any(weights <= 0)
                or not np.allclose(weights.sum(axis=1), 1.0)):
            raise ValueError(f"Invalid mixture weights in {source}")
        emissions = GaussianMixtureEmissions(
            weights=weights, means=means, variances=variances
        )
    else:
        raise ValueError(f"Unsupported emission kind in {source}: {kind!r}")

    return UpperHMM(
        transition_matrix=A,
        emissions=emissions,
    )
