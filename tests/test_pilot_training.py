import json

import numpy as np

from hrc_safety.lhmm.upper import STATES
from hrc_safety.pilot_model import load_upper_hmm, save_upper_hmm
from hrc_safety.pilot_training import fit_trials, leave_one_trial_out, load_trial


def _write_trial(path, trial_id, offset=0.0):
    with path.open("w", encoding="utf-8") as fh:
        for state_index, state in enumerate(STATES):
            for sample_index in range(35):
                feature = {
                    "d": 2.0 - 0.3 * state_index + offset,
                    "v_proj": [0.5, 0.0, -0.5, 1.4][state_index],
                    "v_lat_frac": [0.1, 0.8, 0.1, 0.05][state_index],
                    "a_proj": [0.2, 0.0, -0.2, 1.2][state_index],
                }
                fh.write(json.dumps({
                    "participant_id": "P-test",
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
    model = fit_trials(trials)
    validation = leave_one_trial_out(trials)
    assert validation["accuracy"] > 0.95
    assert validation["hazard_recall"] > 0.95

    target = save_upper_hmm(tmp_path / "model.json", model, validation=validation)
    restored = load_upper_hmm(target)
    np.testing.assert_allclose(restored.A, model.A)
    np.testing.assert_allclose(restored.emissions.means, model.emissions.means)


def test_unlabelled_gap_does_not_create_transition(tmp_path):
    path = tmp_path / "gap.jsonl"
    rows = [
        ("approaching", {"d": 1.5, "v_proj": 0.5, "v_lat_frac": 0.1, "a_proj": 0.1}),
        ("unlabelled", None),
        ("working", {"d": 1.1, "v_proj": 0.0, "v_lat_frac": 0.8, "a_proj": 0.0}),
    ]
    with path.open("w", encoding="utf-8") as fh:
        for label, feature in rows:
            fh.write(json.dumps({"ground_truth": label, "features": feature}) + "\n")
    trial = load_trial(path)
    assert trial.sequences == [["approaching"], ["working"]]
