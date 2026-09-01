"""Experiment-console service tests using the same fake packets as the Xsens bridge."""
from __future__ import annotations

import json
import os
import sys
import threading
import time

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
