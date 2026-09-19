"""Protect the public tutorial's numeric example and hardware-free boundary."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sensor_fusion_demo", REPO / "scripts" / "demo_sensor_fusion.py")
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


def test_tutorial_matches_worked_geometry_without_opening_sockets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The teaching example must not open sockets")
    monkeypatch.setattr(socket, "socket", forbidden)
    report = demo.run_demo()
    assert report["provenance"].startswith("SYNTHETIC")
    assert report["segment_count"] == 23
    np.testing.assert_allclose(report["right_hand_optitrack_m"], [2.3, 3.2, 1.1], atol=1e-6)
    np.testing.assert_allclose(report["right_hand_robot_m"], [1.3, 1.2, 1.1], atol=1e-6)
    assert report["common_translation_hand_error_m"] < 1e-10
    assert report["head_only_turn_hand_error_m"] < 1e-10
    assert not report["first_frame_features_ready"]
    assert report["second_frame_features_ready"]
    assert report["second_frame_body_geometry"]["speed"] > .99
    assert all(not r["available"] for r in report["rejected_examples"].values())


def test_cli_writes_explicitly_synthetic_json_outside_checkout(tmp_path):
    output = tmp_path / "nested" / "example.json"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "demo_sensor_fusion.py"), "--out", str(output)],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report == json.loads(result.stdout)
    assert report["provenance"].startswith("SYNTHETIC")
