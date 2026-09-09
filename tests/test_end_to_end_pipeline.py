"""API dispatch -> parsed sensor frames -> automatic cycle -> persisted data.
All robot IO and clock progression are simulated; no sockets or NIC changes.
"""
import io
import json
from pathlib import Path

import numpy as np
import pytest

import scripts.dashboard_server as service
from hrc_safety.mocap.natnet_bridge import MocapBridge
from hrc_safety.mocap.xsens_transport import build_mxtp02, parse_mxtp02_frame
from hrc_safety.mocap.natnet_transport import build_frame_packet, parse_rigid_body
from tests.test_dashboard_server import FakeGuidedRig


@pytest.mark.parametrize('mode,prefix',[('participant_study','P'),('qualification','Q')])
@pytest.mark.parametrize('block,within,condition,identity',[
    ('A',1,'fixed zone','static'),
    ('B',1,'reactive SSM','dynamic_ssm'),
    ('C',2,'predictive SSM','adaptive'),
])
def test_api_to_saved_automatic_cycle(tmp_path,monkeypatch,mode,prefix,block,within,condition,identity):
    clock=[100.0]
    monkeypatch.setattr(service.time,'monotonic',lambda:clock[0])
    state=service.DashboardState(tmp_path,1,Path('data/models/pilot_hmm.json'),
                                 enable_research_output=True)
    state.optitrack_bridge=MocapBridge(extrinsics=(np.eye(3),np.zeros(3)))

    class Rig(FakeGuidedRig):
        def telemetry_snapshot(self,**kwargs):
            return {'available':True,'source_timestamp_s':clock[0],'source_age_s':0,
                    'actual_tcp_pose':[0,0,2.2,0,0,0],'actual_qd':[0]*6}
        def goto_pose(self,name,*,guard,cancel,speed=.1):
            guard()
            assert not cancel.is_set()
            assert speed == .1
            return super().goto_pose(name)

    rig=Rig()
    state.rig=rig
    runner=service.AutomaticRunController(state,rig,clock=lambda:clock[0],enabled=True)
    handler=service.ApiHandler.__new__(service.ApiHandler)
    handler.state,handler.rig,handler.guided=state,rig,runner
    handler.catalog=service.RunCatalog(tmp_path)
    handler.client_address=('127.0.0.1',1)
    replies=[]
    handler._json=lambda payload,status=200:replies.append((status,payload))

    def post(path,body):
        wire=json.dumps(body).encode()
        handler.path=path
        handler.headers={'Content-Length':str(len(wire))}
        handler.rfile=io.BytesIO(wire)
        handler.do_POST()
        status,payload=replies.pop()
        assert status == 200, payload
        return payload

    counter=[0]
    def feed(seconds=1/60):
        clock[0]+=seconds
        counter[0]+=1
        packet=build_mxtp02({i:(2,0,1) for i in range(1,24)},
                            time_code_ms=int(clock[0]*1000),sample_counter=counter[0])
        frame=parse_mxtp02_frame(packet)
        state.on_xsens_frame(frame)
        state.on_sample(frame['time_code_s'],frame['segments']['1']['position_m'],True,clock[0])
        motive=build_frame_packet(frame_number=counter[0],rigid_bodies={1:((2,0,1),True)})
        number,position,tracked=parse_rigid_body(motive,1)
        state.optitrack_bridge.on_sample(number/120,position,tracked,clock[0])
        state.tick()
        assert state.pipeline_error is None

    def tick(seconds=1/60):
        feed(seconds)
        runner.refresh_health()
        runner.tick()

    feed()
    feed()
    state.mark_calibrated()
    participant=prefix+'07'
    post('/api/protocol/start',{'participant_id':participant,'automatic':True,
         'collection_mode':mode,'mvn_recording_confirmed':True,
         'mvn_recording_reference':participant+'.mvn','motive_recording_reference':participant+'.tak',
         'video_recording_reference':participant+'.mp4','block_label':block,
         'within_block_trial':within,'controller_condition':condition,'planned_event':'clean'})
    post('/api/sync',{})
    tick()
    assert runner.phase == 'loading'  # derivative warm-up cannot advance motion
    tick()
    tick(1)
    tick()
    tick(2)
    assert runner.phase == 'task', runner.reason
    post('/api/protocol/complete',{})
    tick()
    tick(2)
    tick()
    tick(2)
    assert runner.phase == 'complete'
    assert not state.recording
    assert rig.actions.count(('goto','pose2_top')) == 1
    assert rig.actions.count(('goto','pose1_low')) == 1
    assert rig.actions.count(('release','BOTH',0)) == 1
    manifest=json.loads(Path(state.manifest_path).read_text())
    assert manifest['outcome'] == 'completed'
    assert manifest['collection_mode'] == mode
    assert manifest['execution_mode'] == 'automatic'
    rows=[json.loads(line) for line in Path(state.recording_path).read_text().splitlines()]
    assert all(row['participant_id'] == participant for row in rows)
    assert all(row['geometry_reference']['source'] == 'live_rtde_tcp' for row in rows)
    assert all(row['ground_truth_phase'] == 'unlabelled' for row in rows)
    assert {row['controller_decision'].get('condition') for row in rows} == {None,identity}
    events=[json.loads(line) for line in Path(state.event_path).read_text().splitlines()]
    assert any(event['event'] == 'automation_task_contract' for event in events)
