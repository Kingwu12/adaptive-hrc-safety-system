import json

import numpy as np
import pytest

from hrc_safety.config import load_config
from hrc_safety.experiment_diagnostics import ControllerComparison, EventExposure, model_health, release_fingerprint
from hrc_safety.features import FeatureFrame
from hrc_safety.lhmm.upper import UpperHMM
from hrc_safety.pilot_training import fit_trials, load_trial
from tests.test_pilot_training import _write_trial


def test_shared_stop_and_outside_boundary_difference_are_visible():
    hmm = UpperHMM(np.array([[.9,.05,.05],[.05,.9,.05],[.05,.05,.9]]))
    comparison = ControllerComparison(load_config(), hmm)
    close = FeatureFrame(0, .8, 0, 0, 0, 0, 0, 0)
    assert {d['speed_fraction'] for d in comparison.decide(close).values()} == {0}
    far = FeatureFrame(1, 1.1, 0, 0, 0, 0, 0, 0)
    decisions = comparison.decide(far)
    assert decisions['fixed zone']['speed_fraction'] == .35
    assert decisions['reactive SSM']['speed_fraction'] == 1
    assert decisions['predictive SSM']['speed_fraction'] == 1
    assert all(d['shadow_only'] for d in decisions.values())
    np.testing.assert_allclose(hmm.belief, np.full(3, 1/3))


def test_count_fitted_transitions_do_not_freeze_phase_changes(tmp_path):
    path = tmp_path / 'pilot.jsonl'
    _write_trial(path, 'T01')
    trial = load_trial(path)
    model = fit_trials([trial])
    np.testing.assert_allclose(model.A, UpperHMM.fit_transitions(trial.sequences))
    assert not model_health(model)['warnings']
    assert model_health(UpperHMM(np.eye(3)))['warnings']


@pytest.mark.parametrize('metadata', [
    {'collection_mode': 'participant_study'}, {'collection_mode': 'qualification'},
    {'execution_mode': 'automatic'}, {'stale': True},
])
def test_evaluation_and_invalid_capture_cannot_enter_training(tmp_path, metadata):
    path = tmp_path / 'trial.jsonl'
    _write_trial(path, 'T01')
    rows = [json.loads(line) | metadata for line in path.read_text().splitlines()]
    path.write_text('\n'.join(map(json.dumps, rows)))
    assert len(load_trial(path).X) == 0


def test_fingerprint_changes_with_code_and_config(tmp_path):
    base = release_fingerprint(tmp_path, 'model', {'setting': 1})
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/dashboard_server.py').write_text('changed')
    changed = release_fingerprint(tmp_path, 'model', {'setting': 1})
    assert changed['sha256'] != base['sha256']
    assert changed['sha256'] != release_fingerprint(tmp_path, 'model', {'setting': 2})['sha256']
    assert not changed['final_data_approved']


def test_event_label_without_movement_does_not_prove_exposure():
    observer = EventExposure(load_config())
    telemetry = {'available':True,'actual_qd':[0]*6,'source_age_s':0,'source_timestamp_s':1}
    observer.observe({'d':2,'v_proj':1.5}, telemetry, True)
    assert observer.status('rapid intrusion')['motion_samples'] == 0
    assert observer.status('rapid intrusion')['review_reason']
    telemetry['actual_qd'] = [.1]*6
    for source in [2,3]:
        observer.observe({'d':2,'v_proj':.2},telemetry | {'source_timestamp_s':source},True)
    assert observer.status('rapid intrusion')['rapid_closing_samples'] == 0
    assert observer.status('rapid intrusion')['review_reason']


def test_exposure_rejects_duplicate_telemetry_and_flags_intruding_distractor():
    observer = EventExposure(load_config())
    telemetry = {'available':True,'actual_qd':[.1]*6,'source_age_s':0,'source_timestamp_s':1}
    for _ in range(10): observer.observe({'d':.5,'v_proj':1.2},telemetry,True)
    assert observer.motion_samples == 1
    observer.observe({'d':.5,'v_proj':1.2},telemetry | {'source_timestamp_s':2},True)
    assert observer.status('distractor')['review_reason']
    assert observer.status('rapid intrusion')['review_reason'] is None
    assert observer.status('rapid intrusion')['ground_truth_verified'] is False
