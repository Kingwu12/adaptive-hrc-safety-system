import struct

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from hrc_safety.mocap.natnet_transport import build_frame_packet
from hrc_safety.mocap.optitrack_transport import parse_natnet4_marker_sets, RigidBodyMonitor
from hrc_safety.simulated_drilling import SimulatedDrilling, aligned_hands


POINTS = np.array([[0, 0, 1], [0.6, 0, 1], [0.6, 0.5, 1], [0, 0.5, 1]])


def test_corner_identity_survives_packet_reordering_and_panel_rotation():
    detector = SimulatedDrilling(dwell_s=.2)
    events = []
    for i in range(12):
        t = i * .1
        rotation = Rotation.from_euler('z',t)
        offset = np.array([t,0,0])
        world = POINTS @ rotation.as_matrix().T + offset
        target = 0 if i < 6 else 1
        order = np.roll(np.arange(4),i)
        events += detector.observe(t,world[order],{'11':world[target]},
                    source_ids=(i,i,i),fresh=True,task_active=True,
                    panel_pose={'position':offset,'rotation_xyzw':rotation.as_quat()})
    assert events == [0,1]
    assert detector.status()['completed_count'] == 2
    assert detector.fault is None


def test_named_panel_markers_survive_packet_and_monitor():
    packet = build_frame_packet({}, major=4, minor=0, marker_sets={"PANEL": POINTS.tolist()})
    frame, sets = parse_natnet4_marker_sets(packet)
    assert np.allclose(sets["PANEL"], POINTS)
    monitor = RigidBodyMonitor()
    monitor.update_marker_sets(sets, frame / 120, 10)
    snapshot = monitor.marker_snapshot(10.1)
    assert snapshot["age_s"] == pytest.approx(0.1)
    assert snapshot["frame"] == "optitrack"
    monitor.update_marker_sets({}, frame / 120 + 1, 11)
    assert not monitor.marker_snapshot(11)["sets"]


def test_bad_marker_payloads_are_rejected_without_reading_past_declared_size():
    packet = build_frame_packet({}, major=4, minor=0, marker_sets={"PANEL": POINTS.tolist()})
    assert parse_natnet4_marker_sets(packet[:-1]) is None
    assert parse_natnet4_marker_sets(packet[:2] + struct.pack("<H", 8) + packet[4:]) is None
    bad = build_frame_packet({}, major=4, minor=0, marker_sets={"PANEL": [[float("nan"), 0, 0]]})
    assert parse_natnet4_marker_sets(bad) is None


def feed(detector, t, point, *, markers=POINTS, ids=None, fresh=True):
    return detector.observe(t, markers, {"11": point}, source_ids=(t, t) if ids is None else ids,
                            fresh=fresh, task_active=True)


def test_four_hand_dwells_follow_moving_panel_without_real_fastening_claim():
    detector = SimulatedDrilling()
    events = []
    t = 0
    for target in [3, 1, 0, 2]:
        for j in range(17):
            t += 0.125
            angle = t * 0.05
            r = np.array([[np.cos(angle), -np.sin(angle), 0],
                          [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
            moved = POINTS @ r.T + [t * 0.01, 0, 0]
            events += feed(detector, t, moved[target], markers=moved)
    assert events == [3, 1, 0, 2]
    assert detector.status()["simulated_task_complete"]
    assert detector.status()["fastening_verified"] is False
    assert feed(detector, t + 0.125, POINTS[0]) == []
    detector.reset()
    assert detector.status()["completed_count"] == 0


@pytest.mark.parametrize("interruption", ["stale", "gap", "outside", "duplicate", "missing"])
def test_a_pass_or_interrupted_dwell_never_completes_marker(interruption):
    detector = SimulatedDrilling()
    for i in range(9):
        feed(detector, i * 0.125, POINTS[0])
    if interruption == "stale":
        feed(detector, 1.125, POINTS[0], fresh=False)
    elif interruption == "outside":
        feed(detector, 1.125, [5, 5, 5])
    elif interruption == "missing":
        feed(detector, 1.125, POINTS[0], markers=[])
    elif interruption == "duplicate":
        for i in range(20):
            feed(detector, 1.125 + i * 0.125, POINTS[0], ids=(1, 1))
        assert detector.status()["completed_count"] == 0
        return
    for i in range(9):
        feed(detector, 1.5 + i * 0.125, POINTS[0])
    assert detector.status()["completed_count"] == 0


def test_alternating_hands_cannot_accumulate_one_dwell():
    detector = SimulatedDrilling()
    for i in range(40):
        detector.observe(i * 0.125, POINTS, {str(11 if i % 2 else 15): POINTS[0]},
                         source_ids=(i, i), fresh=True, task_active=True)
    assert not detector.completed


@pytest.mark.parametrize("fault", ["clock_reset", "geometry"])
def test_source_or_geometry_change_requires_observer_reset(fault):
    detector = SimulatedDrilling()
    feed(detector, 1, POINTS[0])
    if fault == "clock_reset":
        feed(detector, 1.1, POINTS[0], ids=(0, 0))
    else:
        changed = POINTS.copy()
        changed[0, 0] += 0.1
        feed(detector, 1.1, changed[0], markers=changed)
    for i in range(30):
        feed(detector, 1.2 + i * 0.125, POINTS[0])
    assert detector.status()["fault"] and not detector.completed
    detector.reset()
    assert detector.status()["fault"] is None


def test_alignment_uses_hand_ids_and_rigid_transform_without_identity_fallback():
    frame = {"segments": {"11": {"position_m": [1, 0, 0]}, "15": {"position_m": [0, 1, 0]}}}
    with pytest.raises(ValueError, match="alignment required"):
        aligned_hands(frame, None)
    config = {"accepted": True, "from_frame": "xsens", "to_frame": "optitrack", "units": "m",
              "rotation": [[0, -1, 0], [1, 0, 0], [0, 0, 1]], "translation": [1, 2, 3]}
    assert aligned_hands(frame, config) == {"11": [1, 3, 3], "15": [0, 2, 3]}
    config["rotation"][0][1] = -2
    with pytest.raises(ValueError, match="Invalid rigid"):
        aligned_hands(frame, config)
