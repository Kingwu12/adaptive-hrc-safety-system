"""Experiment-console service tests using the same fake packets as the Xsens bridge."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.dashboard_server import (DashboardState, GuidedRunController,
                                      RigControl, RunCatalog, safe_id)


def _full_xsens_frame() -> dict:
    segments = {
        str(segment_id): {
            "position_m": [float(segment_id), 0.0, 1.0],
            "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
        for segment_id in range(1, 24)
    }
    segments["2"]["quaternion_wxyz"] = [0.5, 0.5, 0.5, 0.5]
    return {
        "message_id": "MXTP02", "sample_counter": 17,
        "datagram_counter": 0, "time_code_s": 1.25,
        "avatar_id": 0, "item_count": 23, "body_segment_count": 23,
        "prop_count": 0, "finger_segment_count": 0, "payload_size": 736,
        "received_monotonic_s": time.monotonic(), "segments": segments,
    }


def test_safe_id_removes_path_characters():
    assert safe_id("../P 01/", "fallback") == "P-01"


def _write_catalog_run(path, participant, trial, labels, stale_at=()):
    session = f"{participant}-{trial}-20260902-120000-abcdef"
    with path.open("w", encoding="utf-8") as handle:
        sample = 0
        for label in labels:
            for _ in range(300):
                handle.write(json.dumps({
                    "session_id": session,
                    "participant_id": participant,
                    "trial_id": trial,
                    "t": sample / 60.0,
                    "stale": sample in stale_at,
                    "ground_truth": label,
                }) + "\n")
                sample += 1


def test_run_catalog_lists_quality_names_and_next_trial(tmp_path):
    labels = [
        "approaching", "working", "retreating", "approaching",
        "working", "hazard", "retreating",
    ]
    _write_catalog_run(tmp_path / "run.jsonl", "P01", "T06", labels, stale_at=(4,))
    catalog = RunCatalog(tmp_path)

    result = catalog.catalog()
    assert result["participants"][0]["id"] == "P01"
    assert result["participants"][0]["next_trial"] == "T07"
    assert result["runs"][0]["quality"]["grade"] == "good"
    assert result["runs"][0]["quality"]["score"] == 100

    saved = catalog.save_participant("Alex Example", "P01")
    assert saved["participant"]["name"] == "Alex Example"
    created = catalog.save_participant("Second Person")
    assert created["participant"]["id"] == "P02"
    assert created["participant"]["next_trial"] == "T01"
    assert (tmp_path / "participants.json").exists()


def test_run_catalog_marks_incomplete_short_attempt_for_repeat(tmp_path):
    _write_catalog_run(tmp_path / "short.jsonl", "P01", "T01", ["unlabelled"])
    catalog = RunCatalog(tmp_path)

    run = catalog.catalog()["runs"][0]
    assert run["quality"]["grade"] == "repeat"
    assert "missing" in " ".join(run["quality"]["reasons"])
    assert RunCatalog._next_trial([{"trial_id": "T01"}, {"trial_id": "T01"}]) == "T03"


def test_dashboard_state_records_enriched_labelled_frames(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    state.on_xsens_frame(_full_xsens_frame())
    base = time.monotonic()
    for i in range(12):
        wall = base + i / 60.0
        position = (1.5 - i * 0.01, 0.2, 1.0)
        state.on_sample(i / 60.0, position, True, wall)
        # OptiTrack supplies the safety-critical absolute position; Xsens is
        # retained as the articulated-motion/logging source.
        state.optitrack_bridge.on_sample(i / 60.0, position, True, wall)
        state.tick()

    snap = state.snapshot()
    assert snap["connected"] is True
    assert snap["xsens_segment_count"] == 23
    assert snap["hmm_state"] in {"approaching", "working", "retreating"}
    assert snap["feature"]["speed"] > 0

    state.mark_calibrated()
    state.start_session(
        "P/01", "T 01", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P01-T01.mvn")
    state.set_label("approaching")
    for i in range(12, 15):
        wall = base + i / 60.0
        position = (1.5 - i * 0.01, 0.2, 1.0)
        state.on_sample(i / 60.0, position, True, wall)
        state.optitrack_bridge.on_sample(i / 60.0, position, True, wall)
        state.tick()
    result = state.stop_session()

    path = tmp_path / result["path"].split("/")[-1]
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    row = next(item for item in rows if item["features"] is not None)
    assert row["participant_id"] == "P-01"
    assert row["schema_version"] == 3
    assert len(row["xsens_frame"]["segments"]) == 23
    assert row["xsens_frame"]["segments"]["2"]["quaternion_wxyz"] == [
        0.5, 0.5, 0.5, 0.5]
    assert row["trial_id"] == "T-01"
    assert row["ground_truth"] == "approaching"
    assert row["ground_truth_phase"] == "approaching"
    assert row["ground_truth_event"] == "none"
    assert row["mvn_native_recording_reference"] == r"C:\MVN\P01-T01.mvn"
    assert row["model_sha256"] == "synthetic-baseline"
    assert row["features"]["v_proj"] > 0
    assert set(row["hmm_posterior"]) == {"approaching", "working", "retreating"}


def test_start_session_resets_temporal_model_state(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    state.on_xsens_frame(_full_xsens_frame())
    base = time.monotonic()
    for i in range(8):
        wall = base + i / 60.0
        position = (1.5 - i * 0.01, 0.2, 1.0)
        state.on_sample(i / 60.0, position, True, wall)
        state.optitrack_bridge.on_sample(i / 60.0, position, True, wall)
        state.tick()

    assert state.feature is not None
    assert state.posterior
    state.mark_calibrated()
    state.start_session(
        "P01", "T01", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P01-T01.mvn")

    assert state.feature is None
    assert state.posterior == {}
    assert state.hmm_state is None
    np.testing.assert_allclose(state.hmm.belief, [1 / 3, 1 / 3, 1 / 3])
    state.stop_session()


def test_dashboard_rejects_recording_without_optitrack(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    with pytest.raises(ValueError, match="OptiTrack"):
        state.start_session("P01", "T07")


def test_dashboard_rejects_incomplete_xsens_body_stream(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    frame = _full_xsens_frame()
    frame["segments"] = {"1": frame["segments"]["1"]}
    frame["item_count"] = frame["body_segment_count"] = 1
    state.on_xsens_frame(frame)
    state.tick()
    with pytest.raises(ValueError, match="received 1/23"):
        state.start_session("P01", "T08")


def test_dashboard_rejects_unmarked_calibration_and_missing_native_reference(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_xsens_frame(_full_xsens_frame())
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.tick()
    with pytest.raises(ValueError, match="calibration"):
        state.start_session(
            "P01", "T09", mvn_recording_confirmed=True,
            mvn_recording_reference=r"C:\MVN\P01-T09.mvn")
    state.mark_calibrated()
    with pytest.raises(ValueError, match="filename"):
        state.start_session("P01", "T09", mvn_recording_confirmed=True)


def test_dashboard_rejects_reused_native_recording_reference(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_xsens_frame(_full_xsens_frame())
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.tick()
    state.mark_calibrated()
    reference = r"C:\MVN\P01-T10.mvn"
    state.start_session(
        "P01", "T10", mvn_recording_confirmed=True,
        mvn_recording_reference=reference)
    later = now + 1 / 60.0
    state.on_sample(1 / 60.0, (0.99, 0.0, 1.0), True, later)
    state.optitrack_bridge.on_sample(
        1 / 60.0, (0.99, 0.0, 1.0), True, later)
    state.tick()
    state.stop_session()
    with pytest.raises(ValueError, match="already used"):
        state.start_session(
            "P01", "T11", mvn_recording_confirmed=True,
            mvn_recording_reference=reference.lower())


def test_guided_protocol_persists_and_applies_labels(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    state.on_xsens_frame(_full_xsens_frame())
    now = time.monotonic()
    state.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.tick()
    state.mark_calibrated()
    state.start_session(
        "P01", "T-guided", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P01-T-guided.mvn")

    first = state.snapshot()
    assert first["guided_step"] == 0
    assert first["label"] == "unlabelled"

    state.advance_guided_protocol()
    second = state.snapshot()
    assert second["guided_step"] == 1
    assert second["label"] == "approaching"

    # The server state, rather than browser-local state, remains authoritative.
    state.advance_guided_protocol()
    third = state.snapshot()
    assert third["guided_step"] == 2
    assert third["label"] == "working"
    state.stop_session()
    stopped = state.snapshot()
    assert stopped["guided_step"] is None
    assert stopped["label"] == "unlabelled"


def test_guided_protocol_requires_active_recording(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    with pytest.raises(ValueError, match="Start guided recording"):
        state.advance_guided_protocol()


def test_rig_status_poll_returns_cached_value_while_probe_is_slow():
    rig = RigControl.__new__(RigControl)
    rig._status_lock = threading.Lock()
    rig._status_refreshing = False
    rig._status_updated = 0.0
    rig._status_cache = {
        "gripper": {"error": "checking rig"},
        "robot": {"reachable": False, "error": "checking rig"},
        "pose": {"available": False, "error": "checking rig"},
    }
    rig.fastening_complete = threading.Event()
    rig.cycle_active = False

    def slow_robot_status():
        time.sleep(0.2)
        return {"reachable": False, "error": "offline"}

    rig.gripper_stats = lambda: {"error": "offline"}
    rig.robot_status = slow_robot_status
    rig.pose_status = lambda: {"available": False, "error": "offline"}

    started = time.monotonic()
    first = rig.status_snapshot({"connected": False})
    assert time.monotonic() - started < 0.1
    assert first["robot"]["error"] == "checking rig"

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with rig._status_lock:
            if not rig._status_refreshing:
                break
        time.sleep(0.01)
    second = rig.status_snapshot({"connected": False}, max_age_s=60.0)
    assert second["robot"]["error"] == "offline"


def test_goto_pose_uses_rtde_and_disconnects(monkeypatch):
    calls = []

    class FakeControl:
        def __init__(self, host):
            calls.append(("connect", host))

        def moveJ(self, q, speed, acceleration):
            calls.append(("moveJ", q, speed, acceleration))
            return True

        def stopJ(self, deceleration):
            calls.append(("stopJ", deceleration))

        def stopScript(self):
            calls.append(("stopScript",))

        def disconnect(self):
            calls.append(("disconnect",))

    monkeypatch.setitem(sys.modules, "rtde_control", types.SimpleNamespace(
        RTDEControlInterface=FakeControl))
    rig = RigControl.__new__(RigControl)
    rig.robot_host = "192.0.2.10"
    rig._poses = {"pose2_top": {"q": [1, 2, 3, 4, 5, 6]}}
    rig.close_program_socket = lambda: calls.append(("close_socket",))
    rig.robot_status = lambda: {
        "reachable": True,
        "robotmode": "Robotmode: RUNNING",
        "safety": "Safetystatus: NORMAL",
    }
    rig.gripper_stats = lambda max_age_s=0.0: {
        "vacuum_A_permille": 600,
        "vacuum_B_permille": 650,
    }

    result = rig.goto_pose("pose2_top")

    assert result["completed"] is True
    assert ("moveJ", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 0.1, 0.15) in calls
    assert calls[-3:] == [("stopJ", 0.5), ("stopScript",), ("disconnect",)]


def test_goto_pose_rejects_low_vacuum_before_connecting(monkeypatch):
    connected = False

    class FakeControl:
        def __init__(self, host):
            nonlocal connected
            connected = True

    monkeypatch.setitem(sys.modules, "rtde_control", types.SimpleNamespace(
        RTDEControlInterface=FakeControl))
    rig = RigControl.__new__(RigControl)
    rig.robot_host = "192.0.2.10"
    rig._poses = {"pose2_top": {"q": [1, 2, 3, 4, 5, 6]}}
    rig.close_program_socket = lambda: None
    rig.robot_status = lambda: {
        "reachable": True,
        "robotmode": "Robotmode: RUNNING",
        "safety": "Safetystatus: NORMAL",
    }
    rig.gripper_stats = lambda max_age_s=0.0: {
        "vacuum_A_permille": 490,
        "vacuum_B_permille": 650,
    }

    with pytest.raises(ValueError, match="vacuum below motion threshold"):
        rig.goto_pose("pose2_top")
    assert connected is False


class FakeGuidedState:
    def __init__(self, step=0, distance=2.0):
        self.config = {"zones": {
            "K": 1.6, "T": 0.4, "C": 0.2, "Sa": 0.1,
            "yellow_margin": 1.6, "hysteresis": 0.05,
        }}
        self.recording = step is not None
        self.step = step
        self.distance = distance
        self.stopped = False
        self.label = "unlabelled" if step in (None, 0, 4, 9) else "retreating"

    def snapshot(self):
        return {
            "recording": self.recording,
            "guided_step": self.step,
            "connected": True,
            "stale": False,
            "optitrack_connected": True,
            "feature": {"d": self.distance},
        }

    def start_session(self, participant, trial,
                      mvn_recording_confirmed=False,
                      mvn_recording_reference=None):
        if not mvn_recording_confirmed:
            raise ValueError("Confirm that native recording is active")
        if not mvn_recording_reference:
            raise ValueError("Enter the visible Windows MVN recording filename")
        self.recording = True
        self.step = 0
        return {"message": "recording", "path": "fake.jsonl"}

    def advance_guided_protocol(self):
        self.step += 1
        return {"message": "advanced", "guided_step": self.step}

    def set_label(self, label):
        self.label = label
        return {"message": f"Ground truth: {label}"}

    def stop_session(self):
        self.recording = False
        self.step = None
        self.stopped = True
        return {"message": "saved", "path": "fake.jsonl"}


class FakeGuidedRig:
    def __init__(self, vacuum=(0, 0), pump=0):
        self.vacuum = vacuum
        self.pump = pump
        self.actions = []
        self._poses = {
            "pose1_low": {"q": [1, 2, 3, 4, 5, 6]},
            "pose2_top": {"q": [6, 5, 4, 3, 2, 1]},
        }
        self.current_q = list(self._poses["pose1_low"]["q"])

    def robot_status(self):
        return {
            "reachable": True,
            "robotmode": "Robotmode: RUNNING",
            "safety": "Safetystatus: NORMAL",
        }

    def pose_status(self):
        return {"available": True, "q": list(self.current_q), "tcp": [0, 0, 0.4]}

    def gripper_stats(self, max_age_s=0.0):
        return {
            "vacuum_A_permille": self.vacuum[0],
            "vacuum_B_permille": self.vacuum[1],
            "pump_rpm": self.pump,
        }

    def gripper_action(self, action, channel, vacuum):
        self.actions.append((action, channel, vacuum))
        if action == "grip":
            self.vacuum = (600, 650)
        else:
            self.vacuum = (0, 0)
        return {
            "ok": True,
            "stats": {
                "vacuum_A_permille": self.vacuum[0],
                "vacuum_B_permille": self.vacuum[1],
            },
        }

    def goto_pose(self, name):
        self.actions.append(("goto", name))
        self.current_q = list(self._poses[name]["q"])
        return {"pose": name, "completed": True}


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def arm_and_confirm(guided, clock, vacuum=60):
    guided.arm_step()
    clock.advance(1.0)
    return guided.complete_step(vacuum)


def test_integrated_guided_actions_grip_lift_lower_release_and_save():
    state = FakeGuidedState(step=2, distance=2.0)
    rig = FakeGuidedRig()
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    arm_and_confirm(guided, clock)
    assert state.step == 3
    assert rig.actions[-1] == ("grip", "BOTH", 60)

    arm_and_confirm(guided, clock)
    assert state.step == 4
    assert rig.actions[-1] == ("goto", "pose2_top")

    state.step = 8
    arm_and_confirm(guided, clock)
    assert state.step == 9
    assert rig.actions[-1] == ("goto", "pose1_low")

    # Once the robot is stationary at low pose, the participant must be able
    # to approach and physically support the panel before suction releases.
    state.distance = 0.5
    result = arm_and_confirm(guided, clock)
    assert result["completed"] is True
    assert state.stopped is True
    assert rig.actions[-1] == ("release", "BOTH", 0)


def test_integrated_guided_motion_is_blocked_inside_clearance_zone():
    state = FakeGuidedState(step=3, distance=1.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    with pytest.raises(ValueError, match="move beyond"):
        arm_and_confirm(guided, clock)
    assert state.step == 3
    assert not rig.actions


def test_integrated_guided_failed_grip_is_released_and_does_not_advance():
    state = FakeGuidedState(step=2, distance=2.0)
    rig = FakeGuidedRig()

    def weak_grip(action, channel, vacuum):
        rig.actions.append((action, channel, vacuum))
        if action == "grip":
            return {"ok": True, "stats": {
                "vacuum_A_permille": 600, "vacuum_B_permille": 200,
            }}
        return {"ok": True, "stats": {
            "vacuum_A_permille": 0, "vacuum_B_permille": 0,
        }}

    rig.gripper_action = weak_grip
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    with pytest.raises(ValueError, match="not verified"):
        arm_and_confirm(guided, clock)
    assert state.step == 2
    assert rig.actions[-1] == ("release", "BOTH", 0)


def test_integrated_guided_start_requires_released_low_rig():
    state = FakeGuidedState(step=None, distance=2.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    guided = GuidedRunController(state, rig)

    with pytest.raises(ValueError, match="suction off"):
        guided.start("P01", "T01")
    assert state.recording is False

    rig.vacuum = (0, 0)
    with pytest.raises(ValueError, match="native recording"):
        guided.start("P01", "T01")
    with pytest.raises(ValueError, match="filename"):
        guided.start("P01", "T01", mvn_recording_confirmed=True)
    result = guided.start(
        "P01", "T01", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P01-T01.mvn")
    assert result["message"] == "recording"
    assert state.recording is True


def test_integrated_guided_physical_action_requires_deliberate_second_press():
    state = FakeGuidedState(step=2, distance=2.0)
    rig = FakeGuidedRig()
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    with pytest.raises(ValueError, match="not armed"):
        guided.complete_step(60)
    assert not rig.actions

    guided.arm_step()
    with pytest.raises(ValueError, match="too fast"):
        guided.complete_step(60)
    assert not rig.actions

    clock.advance(1.0)
    guided.complete_step(60)
    assert rig.actions[-1] == ("grip", "BOTH", 60)


def test_integrated_guided_physical_arm_expires_without_actuating():
    state = FakeGuidedState(step=3, distance=2.0)
    rig = FakeGuidedRig()
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    guided.arm_step()
    clock.advance(5.1)
    with pytest.raises(ValueError, match="expired"):
        guided.complete_step()
    assert not rig.actions
    assert state.step == 3
