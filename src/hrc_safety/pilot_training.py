"""Load labelled dashboard recordings and fit the reported upper HMM."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .lhmm.upper import (STATES, GaussianMixtureEmissions, UpperHMM)
from .metrics import recognition_report

FEATURES = ("d", "v_proj", "speed", "heading_alignment")
_RAW_FEATURE_KEYS = {
    "heading_alignment": "torso_facing",  # legacy capture field; not torso pose
}


@dataclass
class TrialData:
    path: Path
    participant_id: str
    trial_id: str
    X: np.ndarray
    labels: list[str]
    sequences: list[list[str]]
    feature_sequences: list[np.ndarray]
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
    feature_sequences: list[np.ndarray] = []
    current_labels: list[str] = []
    current_rows: list[list[float]] = []
    total = 0
    skipped = 0
    participant_id = "unknown"
    trial_id = source.stem

    def end_segment() -> None:
        nonlocal current_labels, current_rows
        if current_labels:
            sequences.append(current_labels)
            feature_sequences.append(np.asarray(current_rows, dtype=float))
            current_labels = []
            current_rows = []

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
            label = str(
                record.get("ground_truth_phase")
                or record.get("ground_truth")
                or "unlabelled"
            )
            feature = record.get("features")
            if label not in STATES or not isinstance(feature, dict):
                skipped += 1
                end_segment()
                continue
            try:
                vector = []
                for name in FEATURES:
                    if name == "heading_alignment":
                        speed = float(feature.get("speed", 0.0))
                        value = feature.get(
                            "heading_alignment", feature.get("torso_facing")
                        )
                        if value is None:
                            value = (
                                float(feature.get("v_proj", 0.0)) / speed
                                if speed > 1e-9 else 0.0
                            )
                        vector.append(float(value))
                    else:
                        vector.append(float(feature[name]))
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
            current_labels.append(label)
            current_rows.append(vector)
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
        feature_sequences=feature_sequences,
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


def _fit_mixture_emissions(
    X: np.ndarray, labels: list[str], components: int
) -> GaussianMixtureEmissions:
    """Fit deterministic diagonal GMM emissions without adding a runtime dependency."""
    try:
        from sklearn.mixture import GaussianMixture
    except ImportError as exc:  # pragma: no cover - environment-specific guidance
        raise RuntimeError(
            "Gaussian-mixture training requires scikit-learn; install the "
            "project's training extras"
        ) from exc

    weights = []
    means = []
    variances = []
    label_array = np.asarray(labels)
    for state in STATES:
        rows = X[label_array == state]
        if len(rows) < components:
            raise ValueError(
                f"State {state!r} has {len(rows)} samples; cannot fit "
                f"{components} mixture components"
            )
        mixture = GaussianMixture(
            n_components=components,
            covariance_type="diag",
            reg_covar=1e-3,
            random_state=7,
            n_init=3,
            max_iter=200,
        ).fit(rows)
        weights.append(mixture.weights_)
        means.append(mixture.means_)
        variances.append(mixture.covariances_)
    return GaussianMixtureEmissions(
        weights=np.asarray(weights),
        means=np.asarray(means),
        variances=np.asarray(variances),
    )


def fit_trials(
    trials: list[TrialData], emission_components: int = 1,
    transition_power: float = 8.0,
) -> UpperHMM:
    if not trials:
        raise ValueError("No complete labelled trials supplied")
    sequences = [seq for trial in trials for seq in trial.sequences]
    X = np.concatenate([trial.X for trial in trials], axis=0)
    labels = [label for trial in trials for label in trial.labels]
    A = UpperHMM.fit_transitions(sequences, laplace=1.0)
    if transition_power <= 0:
        raise ValueError("transition_power must be positive")
    # Sharpen the fitted row-stochastic transition matrix, then renormalise it.
    # This is a proper probability matrix and encodes the empirically justified
    # persistence of task phases without changing the emission evidence.
    A = np.power(A, float(transition_power))
    A = A / A.sum(axis=1, keepdims=True)
    if emission_components < 1:
        raise ValueError("emission_components must be at least one")
    emissions = (
        UpperHMM.fit_emissions(X, labels, var_floor=1e-3)
        if emission_components == 1
        else _fit_mixture_emissions(X, labels, emission_components)
    )
    return UpperHMM(transition_matrix=A, emissions=emissions)


def _decode_trial(model: UpperHMM, trial: TrialData) -> tuple[list[str], list[str]]:
    """Decode each contiguous labelled segment with a fresh HMM start state.

    Unlabelled or invalid rows deliberately break a sequence during transition
    fitting. Validation must respect the same boundary; otherwise Viterbi silently
    invents temporal continuity across an experimenter reset or tracking gap.
    """
    predictions: list[str] = []
    truth: list[str] = []
    for X_segment, labels_segment in zip(
        trial.feature_sequences, trial.sequences, strict=True
    ):
        predictions.extend(model.viterbi(X_segment))
        truth.extend(labels_segment)
    return predictions, truth


def _filter_trial(model: UpperHMM, trial: TrialData) -> tuple[list[str], list[str]]:
    """Run the causal forward filter, resetting at the same sequence gaps."""
    predictions: list[str] = []
    truth: list[str] = []
    for X_segment, labels_segment in zip(
        trial.feature_sequences, trial.sequences, strict=True
    ):
        model.reset()
        predictions.extend(
            STATES[int(np.argmax(model.step(row)))] for row in X_segment
        )
        truth.extend(labels_segment)
    return predictions, truth


def leave_one_trial_out(
    trials: list[TrialData], emission_components: int = 1,
    transition_power: float = 8.0,
) -> dict:
    """Validate on unseen whole trials so adjacent frames cannot leak across folds."""
    predictions: list[str] = []
    ground_truth: list[str] = []
    online_predictions: list[str] = []
    folds: list[dict] = []
    for held_out in trials:
        training = [trial for trial in trials if trial is not held_out]
        if not training:
            continue
        model = fit_trials(training, emission_components, transition_power)
        predicted, truth = _decode_trial(model, held_out)
        online_predicted, _ = _filter_trial(model, held_out)
        report = recognition_report(predicted, truth)
        online_report = recognition_report(online_predicted, truth)
        predictions.extend(predicted)
        online_predictions.extend(online_predicted)
        ground_truth.extend(truth)
        folds.append({
            "trial_id": held_out.trial_id,
            "accuracy": report.accuracy,
            "balanced_accuracy": report.balanced_accuracy,
            "online_filter_accuracy": online_report.accuracy,
            "per_phase_recall": report.per_state_recall,
        })
    report = recognition_report(predictions, ground_truth)
    online_report = recognition_report(online_predictions, ground_truth)
    return {
        "method": "leave-one-trial-out",
        "accuracy": report.accuracy,
        "balanced_accuracy": report.balanced_accuracy,
        "online_filter_accuracy": online_report.accuracy,
        "online_filter_balanced_accuracy": online_report.balanced_accuracy,
        "per_phase_recall": report.per_state_recall,
        "confusion": report.confusion.tolist(),
        "folds": folds,
    }


def leave_one_participant_out(
    trials: list[TrialData], emission_components: int = 1,
    transition_power: float = 8.0,
) -> dict:
    """Validate on people absent from fitting, not merely unseen adjacent runs."""
    participant_ids = sorted({trial.participant_id for trial in trials})
    if len(participant_ids) < 2:
        raise ValueError("Participant-level validation requires at least two participants")

    predictions: list[str] = []
    ground_truth: list[str] = []
    online_predictions: list[str] = []
    folds: list[dict] = []
    for held_out_id in participant_ids:
        training = [trial for trial in trials
                    if trial.participant_id != held_out_id]
        held_out = [trial for trial in trials
                    if trial.participant_id == held_out_id]
        model = fit_trials(training, emission_components, transition_power)
        fold_predictions: list[str] = []
        fold_online_predictions: list[str] = []
        fold_truth: list[str] = []
        for trial in held_out:
            predicted, truth = _decode_trial(model, trial)
            online_predicted, _ = _filter_trial(model, trial)
            fold_predictions.extend(predicted)
            fold_online_predictions.extend(online_predicted)
            fold_truth.extend(truth)
        report = recognition_report(fold_predictions, fold_truth)
        online_report = recognition_report(fold_online_predictions, fold_truth)
        predictions.extend(fold_predictions)
        online_predictions.extend(fold_online_predictions)
        ground_truth.extend(fold_truth)
        folds.append({
            "participant_id": held_out_id,
            "held_out_trials": len(held_out),
            "training_trials": len(training),
            "accuracy": report.accuracy,
            "balanced_accuracy": report.balanced_accuracy,
            "online_filter_accuracy": online_report.accuracy,
            "per_phase_recall": report.per_state_recall,
            "confusion": report.confusion.tolist(),
        })
    report = recognition_report(predictions, ground_truth)
    online_report = recognition_report(online_predictions, ground_truth)
    return {
        "method": "leave-one-participant-out",
        "participants": participant_ids,
        "accuracy": report.accuracy,
        "balanced_accuracy": report.balanced_accuracy,
        "online_filter_accuracy": online_report.accuracy,
        "online_filter_balanced_accuracy": online_report.balanced_accuracy,
        "per_phase_recall": report.per_state_recall,
        "confusion": report.confusion.tolist(),
        "folds": folds,
    }
