import json

import pytest

from scripts.audit_recorded_trials import audit_trial


@pytest.mark.parametrize('identity,mismatch', [('static',1),('dynamic_ssm',0)])
def test_audit_checks_decision_identity_not_just_assigned_label(tmp_path,identity,mismatch):
    path=tmp_path/'trial.jsonl'
    path.write_text(json.dumps({'controller_condition':'reactive SSM',
                                'controller_decision':{'condition':identity}}))
    result=audit_trial(path)
    assert result['counts'].get('controller_identity_mismatch',0) == mismatch
    assert any('differs from assigned' in s for s in result['unresolved_evidence']) == bool(mismatch)


def test_planned_hazard_label_does_not_prove_robot_motion(tmp_path):
    path = tmp_path / 'trial.jsonl'
    rows = [{'session_id':'synthetic-test', 'planned_event':'rapid intrusion',
             'ground_truth_event':'hazard','sync_marker_count':1,
             'recorded_monotonic_s':i*.02,
             'robot_telemetry':{'available':True,'actual_qd':[0]*6,'source_age_s':0},
             'features':{'d':2,'v_proj':.2}} for i in range(4)]
    path.write_text('\n'.join(map(json.dumps,rows)))
    result = audit_trial(path)
    assert result['counts']['event_window'] == 4
    assert result['counts']['event_during_motion'] == 0
    assert any('no overlap' in item for item in result['unresolved_evidence'])


def test_old_telemetry_is_not_counted_as_measured_motion(tmp_path):
    path=tmp_path/'trial.jsonl'
    path.write_text(json.dumps({'robot_telemetry':{'available':True,'actual_qd':[.1]*6,'source_age_s':1},
                                'recorded_monotonic_s':0}))
    result=audit_trial(path)
    assert result['counts']['measured_motion'] == 0
    assert result['counts']['telemetry_unusable'] == 1


def test_audit_detects_static_geometry_without_rewriting_the_recording(tmp_path):
    path=tmp_path/'trial.jsonl'
    original=json.dumps({'position':[2,0,1], 'features':{'d':2},
                         'robot_telemetry':{'available':True,'actual_tcp_pose':[1.5,0,2.2,0,0,0],
                                            'actual_qd':[0]*6,'source_age_s':0}})
    path.write_text(original)
    result=audit_trial(path)
    assert result['geometry_recomputation']['maximum_absolute_distance_error_m'] == 1.5
    assert any('geometry review' in item for item in result['unresolved_evidence'])
    assert path.read_text() == original


def test_automatic_stream_capture_does_not_require_external_recordings_or_sync_click(tmp_path):
    path=tmp_path/'trial.jsonl'
    path.write_text(json.dumps({'capture_mode':'automatic_streams','sync_marker_count':0}))
    result=audit_trial(path)
    assert not any('shared marker' in item or 'native recordings' in item for item in result['unresolved_evidence'])
    assert any('event onset' in item for item in result['unresolved_evidence'])
