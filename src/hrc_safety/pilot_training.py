"""Load labelled dashboard recordings and fit the reported upper HMM."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .lhmm.upper import STATES, UpperHMM
from .metrics import recognition_report

FEATURES = ("d", "v_proj", "v_lat_frac", "a_proj")


@dataclass
class TrialData:
    path: Path
    participant_id: str
    trial_id: str
    X: np.ndarray
    labels: list[str]
    sequences: list[list[str]]
    total_rows: int
    skipped_rows: int

    @property
    def counts(self) -> Counter:
        return Counter(self.labels)

    def is_complete(self, min_samples_per_state: int) -> bool:
        counts = self.counts
        return all(counts[state] >= min_samples_per_state for state in STATES)


def load_trial(path: str | Path) -> TrialData:
    """Read one JSONL recording, preserving gaps between labelled segments."""
    source = Path(path)
    rows: list[list[float]] = []
    labels: list[str] = []
    sequences: list[list[str]] = []
    current: list[str] = []
    total = 0
    skipped = 0
    participant_id = "unknown"
    trial_id = source.stem

    def end_segment() -> None:
        nonlocal current
        if current:
            sequences.append(current)
            current = []

    with source.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            total += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source}:{line_number}: invalid JSON") from exc
            participant_id = str(record.get("participant_id") or participant_id)
            trial_id = str(record.get("trial_id") or trial_id)
            label = str(record.get("ground_truth") or "unlabelled")
            feature = record.get("features")
            if label not in STATES or not isinstance(feature, dict):
                skipped += 1
                end_segment()
                continue
            try:
                vector = [float(feature[name]) for name in FEATURES]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"{source}:{line_number}: invalid feature vector"
                ) from exc
            if not all(math.isfinite(value) for value in vector):
                skipped += 1
                end_segment()
                continue
            rows.append(vector)
            labels.append(label)
            current.append(label)
    end_segment()

    X = np.asarray(rows, dtype=float)
    if X.size == 0:
        X = np.empty((0, len(FEATURES)), dtype=float)
    return TrialData(
        path=source,
        participant_id=participant_id,
        trial_id=trial_id,
        X=X,
        labels=labels,
        sequences=sequences,
        total_rows=total,
        skipped_rows=skipped,
    )


def load_trials(directory: str | Path) -> list[TrialData]:
    files = sorted(Path(directory).glob("*.jsonl"))
    return [load_trial(path) for path in files]


def complete_trials(
    trials: list[TrialData], min_samples_per_state: int
) -> list[TrialData]:
    return [trial for trial in trials if trial.is_complete(min_samples_per_state)]


def fit_trials(trials: list[TrialData]) -> UpperHMM:
    if not trials:
        raise ValueError("No complete labelled trials supplied")
    sequences = [seq for trial in trials for seq in trial.sequences]
    X = np.concatenate([trial.X for trial in trials], axis=0)
    labels = [label for trial in trials for label in trial.labels]
    A = UpperHMM.fit_transitions(sequences, laplace=1.0)
    emissions = UpperHMM.fit_emissions(X, labels, var_floor=1e-3)
    return UpperHMM(transition_matrix=A, emissions=emissions)


def leave_one_trial_out(trials: list[TrialData]) -> dict:
    """Validate on unseen whole trials so adjacent frames cannot leak across folds."""
    predictions: list[str] = []
    ground_truth: list[str] = []
    folds: list[dict] = []
    for held_out in trials:
        training = [trial for trial in trials if trial is not held_out]
        if not training:
            continue
        model = fit_trials(training)
        predicted = model.viterbi(held_out.X)
        report = recognition_report(predicted, held_out.labels)
        predictions.extend(predicted)
        ground_truth.extend(held_out.labels)
        folds.append({
            "trial_id": held_out.trial_id,
            "accuracy": report.accuracy,
            "hazard_precision": report.hazard_precision,
            "hazard_recall": report.hazard_recall,
        })
    report = recognition_report(predictions, ground_truth)
    return {
        "method": "leave-one-trial-out",
        "accuracy": report.accuracy,
        "hazard_precision": report.hazard_precision,
        "hazard_recall": report.hazard_recall,
        "confusion": report.confusion.tolist(),
        "folds": folds,
    }
