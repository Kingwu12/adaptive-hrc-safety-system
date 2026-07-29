"""Tests for the NatNet bridge: decimation, hold-last, staleness, extrinsics,
Kabsch calibration, and the seam into FeatureExtractor."""
from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from hrc_safety.mocap import MocapBridge  # noqa: E402
from hrc_safety.features import FeatureExtractor  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "calibrate_mocap",
    os.path.join(os.path.dirname(__file__), "..", "scripts",
                 "calibrate_mocap.py"))
calibrate_mocap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(calibrate_mocap)


def test_warmup_returns_none_until_first_tracked_sample():
    b = MocapBridge()
    assert b.tick(0.0) is None
    b.on_sample(100.0, [1, 2, 3], tracked=False, wall_time=0.0)
    assert b.tick(0.01) is None          # untracked frames must not seed
    b.on_sample(100.1, [1, 2, 3], tracked=True, wall_time=0.02)
    assert b.tick(0.03) is not None


def test_dropout_holds_last_position_and_flags_stale():
    b = MocapBridge(staleness_s=0.150)
    b.on_sample(1.0, [0.5, 0.0, 1.0], tracked=True, wall_time=0.0)
    fresh = b.tick(0.10)                  # 100 ms old: held, not stale
    assert not fresh.stale
    assert np.allclose(fresh.position, [0.5, 0.0, 1.0])
    stale = b.tick(0.30)                  # 300 ms old: held, STALE
    assert stale.stale
    assert np.allclose(stale.position, [0.5, 0.0, 1.0])


def test_decimation_tick_sees_latest_of_burst():
    b = MocapBridge()
    for i in range(4):                    # 240 Hz burst between 60 Hz ticks
        b.on_sample(float(i), [i, 0, 0], tracked=True, wall_time=i * 0.004)
    s = b.tick(0.017)
    assert np.allclose(s.position, [3, 0, 0])
    assert s.motive_timestamp == 3.0


def test_extrinsics_applied():
    R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)  # 90 deg about z
    t = np.array([1.0, 0.0, 0.0])
    b = MocapBridge(extrinsics=(R, t))
    b.on_sample(0.0, [1.0, 0.0, 0.0], tracked=True, wall_time=0.0)
    s = b.tick(0.0)
    assert np.allclose(s.position, [1.0, 1.0, 0.0])


def test_kabsch_recovers_known_transform():
    rng = np.random.default_rng(7)
    ang = 0.7
    R_true = np.array([[np.cos(ang), -np.sin(ang), 0],
                       [np.sin(ang), np.cos(ang), 0], [0, 0, 1]])
    t_true = np.array([0.3, -1.2, 0.05])
    mocap = rng.uniform(-2, 2, size=(4, 3))
    robot = mocap @ R_true.T + t_true
    R, t = calibrate_mocap.kabsch(mocap, robot)
    assert np.allclose(R, R_true, atol=1e-9)
    assert np.allclose(t, t_true, atol=1e-9)
    assert np.isclose(np.linalg.det(R), 1.0)


def test_bridge_feeds_feature_extractor_seam():
    """The whole point: bridge output drops straight into push(t, position)."""
    fx = FeatureExtractor(tcp_position=[0.0, 0.0, 2.2])
    b = MocapBridge()
    frame = None
    for k in range(10):                   # operator walking in at 60 Hz
        wall = k / 60.0
        b.on_sample(wall, [2.0 - 0.02 * k, 0.0, 0.0], True, wall_time=wall)
        s = b.tick(wall)
        if s is not None and not s.stale:
            frame = fx.push(s.t, s.position)
    assert frame is not None              # extractor warmed up and emitted
    assert frame.d_dot < 0                # and saw the operator CLOSING


# ---------- Xsens transport (parser + live UDP loopback) ----------

from hrc_safety.mocap.xsens_transport import (  # noqa: E402
    XsensListener, build_mxtp02, parse_mxtp02)


def test_mxtp02_roundtrip_and_segment_select():
    pkt = build_mxtp02({1: (0.1, 0.2, 0.3), 5: (9, 9, 9)}, time_code_ms=2500)
    ts, pos = parse_mxtp02(pkt, segment_id=1)
    assert ts == 2.5 and np.allclose(pos, [0.1, 0.2, 0.3])
    assert parse_mxtp02(pkt, segment_id=7) is None      # absent segment
    assert parse_mxtp02(b"garbage", 1) is None          # malformed: no raise
    assert parse_mxtp02(pkt[:20], 1) is None            # truncated: no raise
    assert parse_mxtp02(b"MXTP01" + pkt[6:], 1) is None  # wrong message type


def test_udp_listener_feeds_bridge_end_to_end():
    import socket as sk
    import time as tm
    b = MocapBridge()
    lst = XsensListener(b, host="127.0.0.1", port=0)     # ephemeral port
    port = lst._sock.getsockname()[1]
    lst.start()
    tx = sk.socket(sk.AF_INET, sk.SOCK_DGRAM)
    tx.sendto(build_mxtp02({1: (1.0, 2.0, 3.0)}, 1000), ("127.0.0.1", port))
    deadline = tm.monotonic() + 2.0
    s = None
    while tm.monotonic() < deadline:
        s = b.tick(tm.monotonic())
        if s is not None:
            break
        tm.sleep(0.01)
    lst.stop(); tx.close()
    assert s is not None and np.allclose(s.position, [1.0, 2.0, 3.0])
    assert s.motive_timestamp == 1.0
