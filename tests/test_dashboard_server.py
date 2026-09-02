"""Experiment-console service tests using the same fake packets as the Xsens bridge."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.dashboard_server import DashboardState, RigControl, safe_id


def test_safe_id_removes_path_characters():
    assert safe_id("../P 01/", "fallback") == "P-01"


def test_dashboard_state_records_enriched_labelled_frames(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
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
    assert snap["hmm_state"] in {"approaching", "working", "retreating", "hazard"}
    assert snap["feature"]["speed"] > 0

    state.mark_calibrated()
    state.start_session("P/01", "T 01")
    state.set_label("approaching")
    state.tick()
    result = state.stop_session()

    path = tmp_path / result["path"].split("/")[-1]
    row = json.loads(path.read_text().splitlines()[0])
    assert row["participant_id"] == "P-01"
    assert row["trial_id"] == "T-01"
    assert row["ground_truth"] == "approaching"
    assert row["features"]["v_proj"] > 0
    assert set(row["hmm_posterior"]) == {"approaching", "working", "retreating", "hazard"}


def test_dashboard_rejects_recording_without_optitrack(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    with pytest.raises(ValueError, match="OptiTrack"):
        state.start_session("P01", "T07")


def test_guided_protocol_persists_and_applies_labels(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.tick()
    state.start_session("P01", "T-guided")

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
