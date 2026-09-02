import json

import numpy as np

from hrc_safety.lhmm.upper import STATES
from hrc_safety.pilot_model import load_upper_hmm, save_upper_hmm
from hrc_safety.pilot_training import (_decode_trial, fit_trials,
                                       leave_one_participant_out,
                                       leave_one_trial_out, load_trial)


def _write_trial(path, trial_id, offset=0.0, participant_id="P-test"):
    with path.open("w", encoding="utf-8") as fh:
        for state_index, state in enumerate(STATES):
            for sample_index in range(35):
                feature = {
                    "d": 2.0 - 0.3 * state_index + offset,
                    "v_proj": [0.5, 0.0, -0.5, 1.4][state_index],
                    "speed": [0.6, 0.1, 0.6, 1.5][state_index],
                    "v_lat_frac": [0.1, 0.8, 0.1, 0.05][state_index],
                    "a_proj": [0.2, 0.0, -0.2, 1.2][state_index],
                }
                fh.write(json.dumps({
                    "participant_id": participant_id,
                    "trial_id": trial_id,
                    "ground_truth": state,
                    "features": feature,
                    "sample_index": sample_index,
                }) + "\n")


def test_load_fit_validate_and_roundtrip_pilot_model(tmp_path):
    paths = [tmp_path / f"trial-{i}.jsonl" for i in range(3)]
    for i, path in enumerate(paths):
        _write_trial(path, f"T{i + 1:02d}", offset=i * 0.01)
    trials = [load_trial(path) for path in paths]

    assert all(trial.is_complete(30) for trial in trials)
    model = fit_trials(trials, emission_components=2)
    validation = leave_one_trial_out(trials, emission_components=2)
    assert validation["accuracy"] > 0.95
    assert validation["balanced_accuracy"] > 0.95

    target = save_upper_hmm(tmp_path / "model.json", model, validation=validation)
    restored = load_upper_hmm(target)
    np.testing.assert_allclose(restored.A, model.A)
    np.testing.assert_allclose(restored.emissions.weights, model.emissions.weights)
    np.testing.assert_allclose(restored.emissions.means, model.emissions.means)


def test_unlabelled_gap_does_not_create_transition(tmp_path):
    path = tmp_path / "gap.jsonl"
    rows = [
        ("approaching", {"d": 1.5, "v_proj": 0.5, "speed": 0.6, "v_lat_frac": 0.1, "a_proj": 0.1}),
        ("unlabelled", None),
        ("working", {"d": 1.1, "v_proj": 0.0, "speed": 0.1, "v_lat_frac": 0.8, "a_proj": 0.0}),
    ]
    with path.open("w", encoding="utf-8") as fh:
        for label, feature in rows:
            fh.write(json.dumps({"ground_truth": label, "features": feature}) + "\n")
    trial = load_trial(path)
    assert trial.sequences == [["approaching"], ["working"]]
    assert [len(segment) for segment in trial.feature_sequences] == [1, 1]


def test_validation_resets_decoder_at_unlabelled_gaps(tmp_path):
    path = tmp_path / "gap.jsonl"
    rows = [
        ("approaching", {"d": 1.5, "v_proj": 0.5, "speed": 0.6, "a_proj": 0.1}),
        ("approaching", {"d": 1.4, "v_proj": 0.5, "speed": 0.6, "a_proj": 0.1}),
        ("unlabelled", None),
        ("working", {"d": 1.1, "v_proj": 0.0, "speed": 0.1, "a_proj": 0.0}),
    ]
    with path.open("w", encoding="utf-8") as fh:
        for label, feature in rows:
            fh.write(json.dumps({"ground_truth": label, "features": feature}) + "\n")
    trial = load_trial(path)

    class RecordingDecoder:
        def __init__(self):
            self.lengths = []

        def viterbi(self, X):
            self.lengths.append(len(X))
            return ["approaching"] * len(X)

    decoder = RecordingDecoder()
    predicted, truth = _decode_trial(decoder, trial)
    assert decoder.lengths == [2, 1]
    assert len(predicted) == len(truth) == 3


def test_leave_one_participant_out_never_trains_on_held_out_person(tmp_path):
    paths = []
    for participant_index, participant_id in enumerate(("P01", "P02", "P03")):
        for trial_index in range(2):
            path = tmp_path / f"{participant_id}-T{trial_index + 1:02d}.jsonl"
            _write_trial(path, f"T{trial_index + 1:02d}",
                         offset=participant_index * 0.01,
                         participant_id=participant_id)
            paths.append(path)
    trials = [load_trial(path) for path in paths]

    validation = leave_one_participant_out(trials)

    assert validation["method"] == "leave-one-participant-out"
    assert validation["participants"] == ["P01", "P02", "P03"]
    assert len(validation["folds"]) == 3
    assert all(fold["held_out_trials"] == 2 for fold in validation["folds"])
    assert validation["accuracy"] > 0.95
