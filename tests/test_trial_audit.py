import json

from scripts.audit_recorded_trials import audit_trial


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
