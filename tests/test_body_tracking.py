import copy
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from hrc_safety.body_tracking import HelmetBodyTracker, BODY_FEATURES
from hrc_safety.config import load_config
from hrc_safety.features import FeatureFrame, BODY_FEATURE_ORDER
from hrc_safety.lhmm.upper import UpperHMM, GaussianEmissions
from hrc_safety.analysis import build_controller
from hrc_safety.pilot_model import load_upper_hmm, save_upper_hmm
from hrc_safety.pilot_training import load_trial, fit_trials


def body_frame(counter=1, t=1., hand=None):
    positions = [(0,0,1), (0,0,1.1), (0,0,1.2), (0,0,1.3), (0,0,1.4),
                 (0,0,1.5), (0,0,1.7), (0,-.2,1.45), (0,-.25,1.4),
                 (.1,-.3,1.2), (.2,-.3,1.1), (0,.2,1.45), (0,.25,1.4),
                 (.1,.3,1.2), (.2,.3,1.1), (0,-.12,.9), (0,-.12,.5),
                 (0,-.12,.1), (.15,-.12,.05), (0,.12,.9), (0,.12,.5),
                 (0,.12,.1), (.15,.12,.05)]
    if hand is not None:
        positions[10] = hand
    return {'sample_counter':counter, 'time_code_s':t,
            'segments':{str(i+1):{'position_m':list(p), 'quaternion_wxyz':[1,0,0,0]}
                        for i,p in enumerate(positions)}}


def helmet(t=1., q=(0,0,0,1)):
    return {'position':[2,3,1.7], 'rotation_xyzw':list(q), 'source_time_s':t, 'age_s':0}


def update(tracker, frame, pose=None, config=None, age=0):
    return tracker.update(frame, pose or helmet(frame['time_code_s']), xsens_age_s=age,
                          config=config or load_config()['helmet_body'],
                          robot_transform=(np.eye(3),np.zeros(3)), tcp=[0,0,2.2])


def test_all_segment_origins_and_orientations_follow_helmet_anchor():
    q = Rotation.from_euler('z', 90, degrees=True).as_quat()
    frame = body_frame()
    result = update(HelmetBodyTracker(), frame, helmet(q=q))
    assert result['available'] and result['segment_count'] == 23
    r = Rotation.from_quat(q).as_matrix()
    head = np.asarray(frame['segments']['7']['position_m'])
    for i in range(1,24):
        expected = [2,3,1.7] + r @ (np.asarray(frame['segments'][str(i)]['position_m']) - head)
        np.testing.assert_allclose(result['segments'][str(i)]['position_optitrack_m'], expected)
        np.testing.assert_allclose(Rotation.from_quat(result['segments'][str(i)]['rotation_optitrack_xyzw']).as_matrix(), r, atol=1e-8)
    shifted = copy.deepcopy(frame)
    for segment in shifted['segments'].values():
        segment['position_m'] = (np.asarray(segment['position_m']) + [100,-40,6]).tolist()
    anchored = update(HelmetBodyTracker(), shifted, helmet(q=q))
    np.testing.assert_allclose(anchored['segments']['11']['position_optitrack_m'], result['segments']['11']['position_optitrack_m'])


def test_turning_only_head_does_not_rotate_the_entire_body():
    frame = body_frame()
    before = update(HelmetBodyTracker(), frame)
    q = Rotation.from_euler('z', 60, degrees=True).as_quat()
    frame['segments']['7']['quaternion_wxyz'] = np.roll(q,1).tolist()
    after = update(HelmetBodyTracker(), frame, helmet(q=q))
    np.testing.assert_allclose(after['segments']['11']['position_optitrack_m'], before['segments']['11']['position_optitrack_m'])


@pytest.mark.parametrize('segment',range(1,24))
def test_every_body_segment_contributes_to_motion_features(segment):
    tracker = HelmetBodyTracker()
    update(tracker, body_frame())
    frame = body_frame(2,1.05)
    frame['segments'][str(segment)]['position_m'][0] += .02
    result = update(tracker,frame)
    assert result['features_ready']
    assert result['features']['mean_segment_speed_m_s'] > 0


@pytest.mark.parametrize('failure',['stale','skew','missing','zero_quaternion','unconfirmed'])
def test_bad_body_sources_do_not_produce_usable_geometry(failure):
    frame, pose, config, age = body_frame(), helmet(), load_config()['helmet_body'], 0
    if failure == 'stale': age = .2
    if failure == 'skew': age = .06
    if failure == 'missing': del frame['segments']['23']
    if failure == 'zero_quaternion': pose['rotation_xyzw'] = [0]*4
    if failure == 'unconfirmed': config['head_axes_confirmed'] = False
    result = update(HelmetBodyTracker(), frame, pose, config, age)
    assert not result['available'] and not result['features_ready']


def test_body_model_receives_body_inputs_and_rejects_missing_values(tmp_path):
    means = np.zeros((3,len(BODY_FEATURE_ORDER)))
    means[:,BODY_FEATURE_ORDER.index('body.right_reach_m')] = [0,1,2]
    model = UpperHMM(np.full((3,3),1/3), GaussianEmissions(means,np.full_like(means,.01)), feature_order=BODY_FEATURE_ORDER)
    path = tmp_path/'model.json'
    save_upper_hmm(path,model)
    model = load_upper_hmm(path)
    assert model.feature_order == BODY_FEATURE_ORDER
    for reach, expected in [(0,'approaching'),(1,'working'),(2,'retreating')]:
        controller = build_controller('adaptive',load_config(),model)
        frame = FeatureFrame(0,2,0,0,0,0,0,0,{**dict.fromkeys(BODY_FEATURES,0), 'right_reach_m':reach})
        assert controller.decide(frame).inferred_state == expected
    with pytest.raises(ValueError,match='body features'):
        FeatureFrame(0,2,0,0,0,0,0,0).as_vector(BODY_FEATURE_ORDER)


def test_body_training_uses_explicit_development_features_and_excludes_evaluation(tmp_path):
    path = tmp_path/'pilot.jsonl'
    rows = []
    for i, label in enumerate(['approaching','working','retreating']):
        for t in range(5):
            rows.append({'participant_id':'P01','collection_mode':'model_development',
                         'body_tracking':{'available':True,'features_ready':True},
                         'ground_truth_phase':label,'features':{'d':2,'v_proj':0,'speed':0,'torso_facing':0,
                         'body_features':dict.fromkeys(BODY_FEATURES,i+t*.01)}})
    path.write_text('\n'.join(map(json.dumps,rows)))
    trial = load_trial(path,BODY_FEATURE_ORDER)
    assert trial.X.shape == (15,len(BODY_FEATURE_ORDER))
    assert fit_trials([trial]).feature_order == BODY_FEATURE_ORDER
    path.write_text('\n'.join(json.dumps(row | {'collection_mode':'participant_study'}) for row in rows))
    assert load_trial(path,BODY_FEATURE_ORDER).X.shape[0] == 0


@pytest.mark.parametrize('condition', ['fixed_zone', 'dynamic_ssm', 'adaptive'])
def test_hand_inside_red_stops_despite_head_being_clear(condition):
    tracker = HelmetBodyTracker()
    pose = helmet()
    pose['position'] = [2,0,1.7]
    update(tracker, body_frame(hand=(-1.5,0,1.1)), pose)
    pose['source_time_s'] = 1.05
    result = update(tracker, body_frame(2,1.05,hand=(-1.5,0,1.1)), pose)
    frame = FeatureFrame(0,2,0,0,0,0,0,0, body_geometry=result['body_geometry'])
    decision = build_controller(condition,load_config(),load_upper_hmm('data/models/pilot_hmm.json')).decide(frame)
    assert decision.d == pytest.approx(.5)
    assert decision.speed_fraction == 0
    assert decision.geometry_source == 'anchored_segment_origins'
    assert frame.as_vector()[0] == 2  # old HMM input retains its trained meaning


def test_body_approach_changes_reactive_control_with_stationary_head():
    tracker = HelmetBodyTracker()
    pose = helmet()
    pose['position'] = [2,0,1.7]
    update(tracker, body_frame(hand=(-.5,0,1.1)), pose)
    pose['source_time_s'] = 1.05
    body = update(tracker, body_frame(2,1.05,hand=(-.6,0,1.1)), pose)
    assert body['body_geometry']['v_proj'] == pytest.approx(2)
    moving = FeatureFrame(0,2,0,0,0,0,0,0,body_geometry=body['body_geometry'])
    still = FeatureFrame(0,2,0,0,0,0,0,0,body_geometry={**body['body_geometry'],'v_proj':0,'speed':0})
    config = load_config()
    assert build_controller('dynamic_ssm',config,None).decide(moving).speed_fraction < build_controller('dynamic_ssm',config,None).decide(still).speed_fraction
    assert build_controller('fixed_zone',config,None).decide(moving).speed_fraction == build_controller('fixed_zone',config,None).decide(still).speed_fraction


def test_body_source_gap_requires_new_velocity_samples():
    tracker = HelmetBodyTracker()
    update(tracker,body_frame())
    assert update(tracker,body_frame(2,1.05))['body_geometry']
    assert update(tracker,body_frame(3,1.3))['body_geometry'] is None
    assert update(tracker,body_frame(4,1.35))['body_geometry']
