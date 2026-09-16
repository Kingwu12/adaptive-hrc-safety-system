"""Exercise the dashboard path, including live geometry and stale-input stops."""
import json
from pathlib import Path

import numpy as np
import pytest

import scripts.dashboard_server as service
from hrc_safety.mocap.natnet_bridge import MocapBridge
from hrc_safety.mocap.xsens_transport import build_mxtp02, parse_mxtp02_frame
from tests.test_dashboard_server import _full_xsens_frame


class LiveRig:
    def __init__(self, clock):
        self.clock = clock
        self.pose = [0,0,2.2,0,0,0]
        self.age = 0
        self.available = True
        self.outputs = []

    def telemetry_snapshot(self, **kwargs):
        return {'available':self.available, 'actual_tcp_pose':self.pose,
                'actual_qd':[0]*6,'source_age_s':self.age,
                'source_timestamp_s':self.clock[0]}

    def apply_research_speed_fraction(self, fraction):
        self.outputs.append(fraction)
        return {'applied':True, 'status':'simulated_output'}


def ready(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(service.time,'monotonic',lambda:clock[0])
    state = service.DashboardState(tmp_path,1,Path('data/models/pilot_hmm.json'),
                                   enable_research_output=True)
    # Isolate live-TCP/capture faults; default body path has separate end-to-end tests.
    state.config['helmet_body']['enabled'] = False
    state.optitrack_bridge = MocapBridge(extrinsics=(np.eye(3), np.zeros(3)))
    rig = LiveRig(clock)
    state.rig = rig

    def feed(xsens=True):
        clock[0] += 1/60
        if xsens:
            state.on_xsens_frame(_full_xsens_frame())
            state.on_sample(clock[0],(2,0,1),True,clock[0])
        state.optitrack_bridge.on_sample(clock[0],(2,0,1),True,clock[0])
        state.tick()

    feed()
    feed()
    state.mark_calibrated()
    return state,rig,clock,feed


def start(state):
    return state.start_session('P07','T01',True,'P07-T01.mvn',
             block_label='A',within_block_trial=1,controller_condition='fixed zone',
             planned_event='clean',collection_mode='participant_study',
             motive_recording_reference='P07-T01.tak',video_recording_reference='P07-T01.mp4')


def test_capture_batches_disk_flushes_without_losing_rows(tmp_path, monkeypatch):
    state, rig, clock, feed = ready(tmp_path, monkeypatch)
    start(state)
    underlying = state.file

    class CountingFile:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.flushes = 0

        def write(self, value):
            return self.wrapped.write(value)

        def flush(self):
            self.flushes += 1
            return self.wrapped.flush()

        def close(self):
            return self.wrapped.close()

    counted = CountingFile(underlying)
    state.file = counted
    for _ in range(10):
        feed()
    assert counted.flushes == 0
    clock[0] += 1.0
    feed()
    assert counted.flushes == 1
    result = state.stop_session()
    rows = Path(result['path']).read_text(encoding='utf-8').splitlines()
    assert len(rows) == 11


def test_missing_body_evidence_keeps_head_distance_visible_but_holds_arm(tmp_path,monkeypatch):
    state,rig,clock,feed = ready(tmp_path,monkeypatch)
    start(state)
    feed()
    feed()
    assert rig.outputs[-1] == 1
    state.config['helmet_body']['enabled'] = True
    feed()
    assert not state.body_tracking['available']
    assert state.feature['d'] == pytest.approx(2)
    assert rig.outputs[-1] == 0
    assert state.controller_decision['status'] == 'body_evidence_unavailable'
    state.stop_session()


def test_q_controller_uses_raw_head_distance_during_xsens_gap(tmp_path, monkeypatch):
    state, rig, clock, feed = ready(tmp_path, monkeypatch)
    state.start_session('Q07', 'T01', True, 'Q07-T01.mvn',
                        block_label='A', within_block_trial=1,
                        controller_condition='fixed zone', planned_event='clean',
                        collection_mode='qualification')
    state.config['helmet_body']['enabled'] = True
    feed()
    feed()
    clock[0] += .2
    feed(xsens=False)
    assert state.feature['d'] == pytest.approx(2)
    assert state.feature['body_geometry'] is None
    assert state.controller_decision['geometry_source'] == 'head_column_proxy'
    assert state.controller_decision['output_applied'] is True
    assert rig.outputs[-1] > 0
    rig.pose = [1, 0, 2.2, 0, 0, 0]
    feed(xsens=False)
    assert state.feature['d'] == pytest.approx(1)
    assert state.controller_decision['speed_fraction'] == pytest.approx(.35)
    assert rig.outputs[-1] == pytest.approx(.35)
    rig.pose = [1.1, 0, 2.2, 0, 0, 0]
    feed(xsens=False)
    assert state.feature['d'] == pytest.approx(.9)
    assert rig.outputs[-1] == 0
    result = state.stop_session()
    row = json.loads(Path(result['path']).read_text().splitlines()[-1])
    assert row['stale'] is True
    assert row['controller_decision']['geometry_source'] == 'head_column_proxy'


def test_aborted_capture_stops_overriding_supervised_recovery_speed(tmp_path, monkeypatch):
    state, rig, clock, feed = ready(tmp_path, monkeypatch)
    start(state)
    feed()
    state.motion_paused = True
    state.stop_session(outcome='aborted')
    before = len(rig.outputs)
    feed()
    assert state.motion_paused is False
    assert state.controller_decision is None
    assert len(rig.outputs) == before


def test_dashboard_uses_moving_robot_pose_for_control_and_recording(tmp_path,monkeypatch):
    state,rig,clock,feed = ready(tmp_path,monkeypatch)
    start(state)
    feed()
    feed()
    assert state.feature['d'] == pytest.approx(2)
    assert rig.outputs[-1] == 1
    rig.pose = [1.5,0,2.2,0,0,0]
    feed()
    assert state.feature['d'] == pytest.approx(.5)
    assert rig.outputs[-1] == 0
    result = state.stop_session()
    rows = [json.loads(line) for line in Path(result['path']).read_text().splitlines()]
    assert rows[-1]['geometry_reference']['tcp_position_m'] == [1.5,0,2.2]
    assert rows[-1]['features']['d'] == pytest.approx(.5)
    assert rows[-1]['robot_telemetry']['actual_tcp_pose'] == rig.pose


@pytest.mark.parametrize('failure',['old_pose','invalid_pose','missing_pose','xsens_dropout'])
def test_geometry_or_sensor_failure_stops_and_logs_staleness(tmp_path,monkeypatch,failure):
    state,rig,clock,feed = ready(tmp_path,monkeypatch)
    start(state)
    feed()
    feed()
    if failure == 'old_pose': rig.age = 1
    if failure == 'invalid_pose': rig.pose = [float('nan')]*6
    if failure == 'missing_pose': rig.available = False
    if failure == 'xsens_dropout':
        state.config['helmet_body']['enabled'] = True
        clock[0] += .2
    feed(xsens=failure != 'xsens_dropout')
    if failure == 'xsens_dropout':
        assert state.feature['d'] == pytest.approx(2)
        assert state.controller_decision['status'] == 'body_evidence_unavailable'
    else:
        assert state.feature is None
    assert rig.outputs[-1] == 0
    result = state.stop_session()
    row = json.loads(Path(result['path']).read_text().splitlines()[-1])
    if failure == 'invalid_pose':
        # A deliberately corrupt telemetry provider must not emit non-JSON NaN.
        assert state.pipeline_error is not None
        assert 'NaN' not in Path(result['path']).read_text()
    else:
        assert row['stale'] is True
        assert row['controller_decision']['speed_fraction'] == 0


def test_structured_start_does_not_accept_configured_tcp_fallback(tmp_path,monkeypatch):
    state,rig,clock,feed = ready(tmp_path,monkeypatch)
    rig.available = False
    with pytest.raises(ValueError,match='fresh live robot TCP'):
        start(state)
    assert not state.recording
    assert rig.outputs == []


@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf')])
def test_invalid_non_pelvis_xsens_item_is_rejected(value):
    packet = build_mxtp02({1:(0,0,1),11:(value,0,1)})
    assert parse_mxtp02_frame(packet) is None


def test_capture_write_failure_latches_zero_and_surfaces_error(tmp_path,monkeypatch):
    state,rig,clock,feed=ready(tmp_path,monkeypatch)
    start(state)
    feed()
    feed()
    original=state.file
    class FullDisk:
        def write(self,*args): raise OSError('test recording disk full')
        def close(self): original.close()
    state.file=FullDisk()
    feed()
    assert rig.outputs[-1] == 0
    assert 'disk full' in state.snapshot()['pipeline_error']
    state.file=original
    feed()
    assert rig.outputs[-1] == 0  # no implicit recovery after the error
    state.stop_session()
    with pytest.raises(ValueError,match='pipeline failed'):
        start(state)


@pytest.mark.parametrize('outcome,completed',[('aborted',False),('completed',True),(None,False)])
def test_old_good_capture_summary_requires_separate_completion_evidence(tmp_path,outcome,completed):
    path=tmp_path/'P07-T01.jsonl'
    path.write_text('{}\n')
    summary={'session_id':path.stem,'file_name':path.name,'participant_id':'P07',
             'trial_id':'T01','collection_mode':'participant_study','started_at':'2026-09-09',
             'quality':{'grade':'good','score':100},'duration_s':40,'samples':2400}
    manifest={'session_id':path.stem,'outcome':outcome,'catalog_summary':summary}
    manifest_path=path.with_suffix('.manifest.json')
    original=json.dumps(manifest)
    manifest_path.write_text(original)
    result=service.RunCatalog(tmp_path).catalog()['runs'][0]
    assert result['completed'] is completed
    assert result['quality']['grade'] == 'good'  # capture quality remains historical
    assert manifest_path.read_text() == original
