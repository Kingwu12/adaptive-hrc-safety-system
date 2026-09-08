"""No-hardware qualification of the integrated automatic panel cycle."""
import threading
import types
import sys

import pytest

from test_dashboard_server import FakeClock, FakeGuidedState, FakeGuidedRig
from scripts.dashboard_server import AutomaticRunController, RigControl, RunCatalog, ApiHandler


class State(FakeGuidedState):
    def __init__(self, clock):
        super().__init__(step=None)
        self.clock = clock
        self.controller_updated_at = clock()
        self.events = []
        self.fresh = True
        self.output = True
        self.sync_count = 0

    def snapshot(self):
        return {**super().snapshot(), "stale": not self.fresh, "xsens_segment_count": 23,
                "sync_marker_count": self.sync_count,
                "controller_decision": {"output_applied": self.output}}

    def start_session(self, *args, **kwargs):
        return super().start_session(*args[:4])

    def journal_event(self, kind, **payload):
        self.events.append({"event": kind, **payload})


class Rig(FakeGuidedRig):
    def telemetry_snapshot(self):
        return {"available": True, "actual_qd": [0.0] * 6, "source_age_s": 0.0}

    def goto_pose(self, name, *, guard, cancel):
        guard()
        assert not cancel.is_set()
        return super().goto_pose(name)

    def robot_action(self, action):
        self.actions.append((action,))
        return {"action": action}


def setup():
    clock = FakeClock()
    state, rig = State(clock), Rig()
    runner = AutomaticRunController(state, rig, clock, enabled=True)
    runner.start("Q01", "T01", True, "Q01-T01.mvn",
                 collection_mode="qualification", block_label="A", automatic=True)
    return clock, state, rig, runner


def tick(clock, state, runner, seconds=0):
    clock.advance(seconds)
    state.controller_updated_at = clock()
    runner.refresh_health()
    runner.tick()


def begin(clock, runner):
    # Only the existing sync marker is needed. Suction is already on from start.
    assert runner.rig.actions == [("grip", "BOTH", 60)]
    runner.state.sync_count = 1


def test_full_automatic_cycle_moves_once_each_and_never_releases_overhead():
    clock, state, rig, runner = setup()
    begin(clock, runner)
    assert runner.phase == "loading"
    tick(clock, state, runner)
    tick(clock, state, runner, 1)
    assert runner.phase == "retreat_lift"
    assert state.step == 3
    assert not any(a[0] == "goto" for a in rig.actions)
    tick(clock, state, runner)
    tick(clock, state, runner, 2)
    assert runner.phase == "task"
    assert state.step == 7
    assert state.label == "unlabelled"
    assert rig.actions.count(("goto", "pose2_top")) == 1
    assert not any(a[0] == "release" for a in rig.actions)
    tick(clock, state, runner, 2)
    assert runner.phase == "task"  # retreat alone is not task completion
    runner.complete_step()
    tick(clock, state, runner)
    tick(clock, state, runner, 2)
    assert runner.phase == "supported_release"
    assert rig.actions.count(("goto", "pose1_low")) == 1
    with pytest.raises(ValueError, match="not armed"):
        runner.complete_step()
    runner.arm_step()
    clock.advance(1)
    result = runner.complete_step()
    assert result["completed"] and state.stopped
    assert rig.actions[-1] == ("release", "BOTH", 0)
    assert runner.phase == "complete"
    assert state.actions == [("event_start", "automatic_lift"), ("event_end", "automatic_lift")]


def test_clearance_dwell_resets_on_reentry():
    clock, state, rig, runner = setup()
    begin(clock, runner)
    tick(clock, state, runner)
    tick(clock, state, runner, 1)
    tick(clock, state, runner)
    state.distance = 0.5
    tick(clock, state, runner, 1)
    state.distance = 2.0
    tick(clock, state, runner, 1)
    tick(clock, state, runner, 1)
    assert runner.phase == "retreat_lift"
    assert not any(a[0] == "goto" for a in rig.actions)
    tick(clock, state, runner, 1)
    assert runner.phase == "task"


@pytest.mark.parametrize("failure", ["grip", "tracking", "nan", "stale_health", "output"])
def test_faults_latch_without_release_or_restart(failure):
    clock, state, rig, runner = setup()
    begin(clock, runner)
    tick(clock, state, runner)
    tick(clock, state, runner, 1)
    tick(clock, state, runner)
    if failure == "grip":
        rig.vacuum = (600, 200)
    elif failure == "tracking":
        state.fresh = False
    elif failure == "nan":
        state.distance = float("nan")
    elif failure == "output":
        state.output = False
    if failure == "stale_health":
        clock.advance(3)
        runner.tick()
    else:
        tick(clock, state, runner, 2)
    assert runner.phase == "fault"
    assert runner.cancel.is_set()
    assert ("stop",) in rig.actions
    assert not any(a[0] == "release" for a in rig.actions)
    state.fresh, state.output, state.distance = True, True, 2.0
    rig.vacuum = (650, 650)
    tick(clock, state, runner, 3)
    assert runner.phase == "fault"
    with pytest.raises(ValueError, match="faulted"):
        runner.complete_step()


def test_seal_dwell_resets_and_low_pressure_during_loading_does_not_vent():
    clock, state, rig, runner = setup()
    begin(clock, runner)
    tick(clock, state, runner)
    rig.vacuum = (200, 600)
    tick(clock, state, runner, 0.8)
    rig.vacuum = (600, 600)
    tick(clock, state, runner, 0.8)
    assert runner.phase == "loading"
    tick(clock, state, runner, 1)
    assert runner.phase == "retreat_lift"
    assert not any(a[0] == "release" for a in rig.actions)


def test_auto_start_gate_and_manual_step_bypass():
    clock, state, rig, runner = setup()
    begin(clock, runner)
    with pytest.raises(ValueError, match="automatically"):
        runner.complete_step()
    state.recording = False
    with pytest.raises(ValueError, match="participant release is not validated"):
        runner.start("P01", "T01", True, "P01.mvn", automatic=True,
                     collection_mode="participant_study")
    runner.enabled = False
    with pytest.raises(ValueError, match="enable-automatic-trials"):
        runner.start("Q01", "T01", True, "Q01.mvn", automatic=True,
                     collection_mode="qualification")


def test_loading_timeout_stops_without_venting():
    clock, state, rig, runner = setup()
    begin(clock, runner)
    rig.vacuum = (0, 0)
    tick(clock, state, runner, 121)
    assert runner.phase == "fault"
    assert not any(a[0] == "release" for a in rig.actions)


def test_gripper_failed_refresh_does_not_return_old_good_pressure():
    rig = RigControl.__new__(RigControl)
    rig.lock = threading.Lock()
    rig._last_gripper_t = 0
    rig._last_gripper = {"vacuum_A_permille": 650, "vacuum_B_permille": 650}
    rig.gripper = types.SimpleNamespace(stats=lambda: {"ok": False, "error": "offline"})
    assert rig.gripper_stats(max_age_s=0) == {"error": "offline"}


@pytest.mark.parametrize("failure", [None, "guard", "cancel", "wrong_pose", "watchdog"])
def test_async_move_watchdog_interrupt_and_pose_confirmation(monkeypatch, failure):
    calls = []
    cancel = threading.Event()

    class Control:
        def __init__(self, host): pass
        def setWatchdog(self, hz):
            calls.append("watchdog")
            return failure != "watchdog"
        def moveJ(self, q, s, a, asynchronous):
            assert asynchronous
            calls.append("move")
            if failure == "cancel": cancel.set()
            return True
        def kickWatchdog(self): calls.append("kick"); return True
        def getAsyncOperationProgress(self): return -1
        def stopJ(self, a): calls.append("stop")
        def stopScript(self): calls.append("stopScript")
        def disconnect(self): calls.append("disconnect")

    monkeypatch.setitem(sys.modules, "rtde_control", types.SimpleNamespace(RTDEControlInterface=Control))
    rig = RigControl.__new__(RigControl)
    rig.robot_host = "192.0.2.1"
    rig._poses = {"top": {"q": [1] * 6}}
    rig.close_program_socket = lambda: None
    rig.robot_status = lambda: {"reachable": True, "robotmode": "RUNNING", "safety": "NORMAL"}
    rig.gripper_stats = lambda **kwargs: {"vacuum_A_permille": 600, "vacuum_B_permille": 600}
    rig.pose_status = lambda: {"available": True, "q": [0 if failure == "wrong_pose" else 1] * 6}

    def guard():
        if failure == "guard" and "move" in calls:
            raise ValueError("lost telemetry")

    if failure:
        with pytest.raises(ValueError):
            rig.goto_pose("top", guard=guard, cancel=cancel)
    else:
        assert rig.goto_pose("top", guard=guard, cancel=cancel)["completed"]
    assert calls[-3:] == ["stop", "stopScript", "disconnect"]


def test_controller_can_slow_or_stop_during_event_without_task_reselection():
    clock, state, rig, runner = setup()
    begin(clock, runner)
    tick(clock, state, runner)
    tick(clock, state, runner, 1)
    state.controller_updated_at = clock()
    state.distance = 0.3
    # Launch clearance is separate. During motion the selected controller,
    # not the sequencer's common starting-distance gate, owns speed reduction.
    runner._motion_guard()


def test_automatic_capture_quality_does_not_require_fabricated_human_labels():
    quality = RunCatalog._quality(3000, 60, 50, 0, {"unlabelled": 3000}, [], 0,
                                  {}, "clean", automatic=True, completed=True)
    assert quality["grade"] == "good"
    assert "video annotation" in quality["reasons"][0]
    aborted = RunCatalog._quality(3000, 60, 50, 0, {"unlabelled": 3000}, [], 0,
                                  {}, "clean", automatic=True, completed=False)
    assert aborted["grade"] == "repeat"


def test_stop_request_does_not_wait_for_motion_lock():
    clock, state, rig, runner = setup()
    runner.lock.acquire()
    thread = threading.Thread(target=runner.request_stop)
    thread.start()
    thread.join(timeout=1)
    runner.lock.release()
    assert not thread.is_alive()
    assert runner.cancel.is_set()


def request(runner, state, rig, path, body, remote=False, key=""):
    import io
    import json
    handler = ApiHandler.__new__(ApiHandler)
    handler.guided, handler.state, handler.rig = runner, state, rig
    handler.path = path
    handler.client_address = ("192.0.2.1" if remote else "127.0.0.1", 1234)
    payload = json.dumps(body).encode()
    handler.rfile = io.BytesIO(payload)
    handler.headers = {"Content-Length": str(len(payload)), "X-Control-Key": key}
    handler.control_key = "test-key"
    handler.allow_remote_control = False
    replies = []
    handler._json = lambda result, code=200: replies.append((code, result))
    handler.do_POST()
    return replies[0]


@pytest.mark.parametrize("path,body", [
    ("/api/gripper", {"action": "release"}),
    ("/api/robot", {"action": "go_up"}),
    ("/api/demo", {"action": "start"}),
    ("/api/protocol/advance", {}),
    ("/api/label", {"label": "working"}),
])
def test_http_manual_bypasses_rejected_during_automatic_trial(path, body):
    clock, state, rig, runner = setup()
    before = list(rig.actions)
    code, _ = request(runner, state, rig, path, body)
    assert code == 400
    assert rig.actions == before


def test_remote_abort_requires_key_and_preserves_attempt_even_when_stop_fails():
    clock, state, rig, runner = setup()
    code, _ = request(runner, state, rig, "/api/session/stop", {}, remote=True)
    assert code == 403 and not runner.cancel.is_set()

    def fail(_action): raise OSError("robot connection lost")
    rig.robot_action = fail
    code, result = request(runner, state, rig, "/api/session/stop", {}, remote=True, key="test-key")
    assert code == 200
    assert "STOP UNCONFIRMED" in result["message"]
    assert state.stopped and runner.cancel.is_set()


def test_recorded_automatic_steps_never_become_hmm_ground_truth(tmp_path):
    import json
    import time
    from pathlib import Path
    from test_dashboard_server import _full_xsens_frame
    from scripts.dashboard_server import DashboardState

    state = DashboardState(tmp_path, segment_id=1, model_path=Path("data/models/pilot_hmm.json"))
    state.on_xsens_frame(_full_xsens_frame())
    now = time.monotonic()
    state.on_sample(0, (2, 0, 1), True, now)
    state.optitrack_bridge.on_sample(0, (2, 0, 1), True, now)
    state.tick()
    state.mark_calibrated()
    state.start_session("Q01", "T01", True, "auto-test.mvn", execution_mode="automatic")
    state.mark_sync_event()
    state.advance_guided_protocol()
    assert state.snapshot()["label"] == "unlabelled"
    state.tick()
    result = state.stop_session()
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["execution_mode"] == "automatic"
    rows = [json.loads(line) for line in Path(result["path"]).read_text().splitlines()]
    assert rows and all(r["ground_truth_phase"] == "unlabelled" for r in rows)
    assert all(r["execution_mode"] == "automatic" for r in rows)


def test_speed_output_is_reconfirmed_instead_of_cached_forever():
    import time
    rig = RigControl.__new__(RigControl)
    rig._output_lock = threading.Lock()
    rig._last_speed_fraction = 0.5
    rig._last_speed_write_at = time.monotonic() - 1
    writes = []
    rig._io = types.SimpleNamespace(setSpeedSlider=lambda value: writes.append(value) or False)
    result = rig.apply_research_speed_fraction(0.5)
    assert writes == [0.5]
    assert not result["applied"] and rig._last_speed_fraction is None


@pytest.mark.parametrize("qd,age", [(0.1, 0.0), (0.0, 1.0)])
def test_release_is_blocked_without_stationary_telemetry(qd, age):
    clock, state, rig, runner = setup()
    state.step = 9
    runner.phase = "supported_release"
    rig.telemetry_snapshot = lambda: {"available": True, "actual_qd": [qd] * 6, "source_age_s": age}
    runner.arm_step()
    clock.advance(1)
    with pytest.raises(ValueError, match="stationary"):
        runner.complete_step()
    assert not any(a[0] == "release" for a in rig.actions)


def test_catalog_rechecks_completed_manifest_and_keeps_block_trial_slot(tmp_path):
    import json
    path = tmp_path / "Q01-T01-test.jsonl"
    rows = [json.dumps({"session_id": path.stem, "participant_id": "Q01",
                        "trial_id": "T01", "t": i / 50,
                        "collection_mode": "qualification", "execution_mode": "automatic",
                        "block_label": "A", "within_block_trial": 1,
                        "planned_event": "clean", "ground_truth_phase": "unlabelled"})
            for i in range(3001)]
    path.write_text("\n".join(rows) + "\n")
    catalog = RunCatalog(tmp_path)
    assert catalog.catalog()["runs"][0]["quality"]["grade"] == "repeat"
    path.with_suffix(".manifest.json").write_text(json.dumps({
        "session_id": path.stem, "outcome": "completed", "execution_mode": "automatic"}))
    run = catalog.catalog()["runs"][0]
    assert run["quality"]["grade"] == "good"
    assert run["within_block_trial"] == 1 and run["block_label"] == "A"


def test_trial_start_turns_suction_on_once_without_any_arm_or_complete_request():
    clock, state, rig, runner = setup()
    assert runner.phase == "loading" and state.step == 0
    assert rig.actions == [("grip", "BOTH", 60)]
    assert not any(a[0] == "goto" for a in rig.actions)
    with pytest.raises(ValueError, match="already active"):
        runner.start("Q01", "T01", True, "another.mvn", automatic=True,
                     collection_mode="qualification")
    with pytest.raises(ValueError, match="Only supported release"):
        runner.arm_step()
    assert rig.actions == [("grip", "BOTH", 60)]


def test_missing_sync_keeps_suction_on_but_cannot_advance_to_motion():
    clock, state, rig, runner = setup()
    for _ in range(10):
        tick(clock, state, runner, 1)
    assert state.step == 0 and runner.phase == "loading"
    assert rig.actions == [("grip", "BOTH", 60)]
    state.sync_count = 1
    tick(clock, state, runner)
    assert state.step == 1  # still needs a fresh stable-seal interval
    tick(clock, state, runner, 1)
    assert state.step == 3


@pytest.mark.parametrize("failure", ["moving", "wrong_pose", "gripper_command", "gripper_read", "cancel"])
def test_automatic_suction_start_failures_do_not_trigger_motion_or_vent(failure):
    clock = FakeClock()
    state, rig = State(clock), Rig()
    runner = AutomaticRunController(state, rig, clock, enabled=True)
    if failure == "moving":
        rig.telemetry_snapshot = lambda: {"available": True, "actual_qd": [0.1] * 6, "source_age_s": 0}
    elif failure == "wrong_pose":
        rig.current_q = list(rig._poses["pose2_top"]["q"])
    else:
        original = rig.gripper_action

        def action(*args):
            result = original(*args)
            if failure == "gripper_command":
                return {"ok": False, "error": "command rejected"}
            if failure == "gripper_read":
                rig.gripper_stats = lambda **kwargs: {"error": "read failed"}
            if failure == "cancel":
                runner.request_stop("Stop during suction startup")
            return result
        rig.gripper_action = action
    with pytest.raises(ValueError):
        runner.start("Q01", "T01", True, "failed.mvn", automatic=True,
                     collection_mode="qualification", block_label="A")
    assert not any(a[0] in ("goto", "release") for a in rig.actions)
    if failure in ("moving", "wrong_pose"):
        assert not rig.actions and not state.recording
    else:
        assert runner.phase == "fault" and runner.cancel.is_set()
        assert state.recording  # failed attempt retained for abort/save
