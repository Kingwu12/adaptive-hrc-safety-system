"""Persistence for a pilot-fitted upper HMM.

The JSON artifact is deliberately small and contains fitted parameters plus
validation metadata, never raw participant frames.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .lhmm.upper import STATES, GaussianEmissions, UpperHMM

MODEL_SCHEMA_VERSION = 1


def model_payload(hmm: UpperHMM, **metadata) -> dict:
    """Return a JSON-serialisable representation of a fitted upper HMM."""
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "states": list(STATES),
        "feature_order": ["d", "v_proj", "v_lat_frac", "a_proj"],
        "transition_matrix": hmm.A.tolist(),
        "emissions": {
            "means": hmm.emissions.means.tolist(),
            "variances": hmm.emissions.variances.tolist(),
        },
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

    A = np.asarray(payload["transition_matrix"], dtype=float)
    means = np.asarray(payload["emissions"]["means"], dtype=float)
    variances = np.asarray(payload["emissions"]["variances"], dtype=float)
    if A.shape != (len(STATES), len(STATES)):
        raise ValueError(f"Invalid transition matrix shape in {source}: {A.shape}")
    if means.shape != (len(STATES), 4) or variances.shape != means.shape:
        raise ValueError(f"Invalid emission shape in {source}")
    if not np.isfinite(A).all() or not np.isfinite(means).all():
        raise ValueError(f"Non-finite model parameter in {source}")
    if not np.isfinite(variances).all() or np.any(variances <= 0):
        raise ValueError(f"Invalid emission variance in {source}")
    if not np.allclose(A.sum(axis=1), 1.0):
        raise ValueError(f"Transition rows do not sum to one in {source}")

    return UpperHMM(
        transition_matrix=A,
        emissions=GaussianEmissions(means=means, variances=variances),
    )
