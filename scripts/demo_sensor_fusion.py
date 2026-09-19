#!/usr/bin/env python3
"""Synthetic Xsens/OptiTrack anchoring tutorial; no sockets or robot access.

Run from a checkout with numpy/scipy installed:
    python scripts/demo_sensor_fusion.py
    python scripts/demo_sensor_fusion.py --out work/synthetic-fusion-demo.json

The demonstration uses the production MXTP02 parser and HelmetBodyTracker.
Its values are teaching examples, never participant observations.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hrc_safety.body_tracking import HelmetBodyTracker  # noqa: E402
from hrc_safety.mocap.xsens_transport import (  # noqa: E402
    build_mxtp02, parse_mxtp02_frame,
)

# One plausible but entirely invented 23-segment pose, in MXTP02 ID order.
POSITIONS_M = (
    (0, 0, 1), (0, 0, 1.1), (0, 0, 1.2), (0, 0, 1.3),
    (0, 0, 1.4), (0, 0, 1.5), (0, 0, 1.7),
    (0, -.2, 1.45), (0, -.25, 1.4), (.1, -.3, 1.2), (.2, -.3, 1.1),
    (0, .2, 1.45), (0, .25, 1.4), (.1, .3, 1.2), (.2, .3, 1.1),
    (0, -.12, .9), (0, -.12, .5), (0, -.12, .1), (.15, -.12, .05),
    (0, .12, .9), (0, .12, .5), (0, .12, .1), (.15, .12, .05),
)
MOUNT = {
    "enabled": True,
    "head_axes_confirmed": True,
    "head_to_helmet_rotation": np.eye(3).tolist(),
    "head_origin_in_helmet_m": [0, 0, 0],
}
# Deliberately independent of the recorded lab calibration and robot config.
ROBOT_TRANSFORM = (np.eye(3), np.array([-1., -2., 0.]))
SYNTHETIC_TCP = [0., 0., 2.2]


def synthetic_frame(counter=1, time_ms=1000):
    packet = build_mxtp02(
        {i: p for i, p in enumerate(POSITIONS_M, start=1)},
        sample_counter=counter, time_code_ms=time_ms,
    )
    frame = parse_mxtp02_frame(packet)
    if frame is None:
        raise RuntimeError("Synthetic MXTP02 packet failed production parsing")
    return frame


def synthetic_helmet(source_time=1., yaw_deg=90.):
    return {
        "position": [2., 3., 1.7],
        "rotation_xyzw": Rotation.from_euler("z", yaw_deg, degrees=True).as_quat().tolist(),
        "source_time_s": source_time,
        "age_s": .01,
    }


def observe(tracker, frame, helmet, age=.01):
    return tracker.update(
        frame, helmet, xsens_age_s=age, config=MOUNT,
        robot_transform=ROBOT_TRANSFORM, tcp=SYNTHETIC_TCP,
    )


def hand(result, frame_name="optitrack"):
    if not result["available"]:
        raise RuntimeError(result["reason"])
    return np.asarray(result["segments"]["11"][f"position_{frame_name}_m"])


def run_demo():
    frame, helmet = synthetic_frame(), synthetic_helmet()
    tracker = HelmetBodyTracker()
    baseline = observe(tracker, frame, helmet)

    # A translation shared by every segment cancels in (segment - head).
    shifted = copy.deepcopy(frame)
    for segment in shifted["segments"].values():
        segment["position_m"] = (
            np.asarray(segment["position_m"]) + [100., -40., 6.]
        ).tolist()
    translated = observe(HelmetBodyTracker(), shifted, helmet)

    # Only the anatomical head and optical helmet turn by another 60 degrees.
    turned = copy.deepcopy(frame)
    head_quat_xyzw = Rotation.from_euler("z", 60, degrees=True).as_quat()
    turned["segments"]["7"]["quaternion_wxyz"] = np.roll(head_quat_xyzw, 1).tolist()
    head_turned = observe(HelmetBodyTracker(), turned, synthetic_helmet(yaw_deg=150))

    # A second advancing pair moves the optical anchor 5 cm in 50 ms.
    next_helmet = synthetic_helmet(source_time=1.05)
    next_helmet["position"][0] -= .05
    moving = observe(tracker, synthetic_frame(2, 1050), next_helmet)
    if not moving["features_ready"]:
        raise RuntimeError("Second advancing pair did not produce motion features")

    stale = observe(HelmetBodyTracker(), frame, helmet, age=.20)
    skewed = observe(HelmetBodyTracker(), frame, helmet, age=.08)
    incomplete = copy.deepcopy(frame)
    del incomplete["segments"]["23"]
    missing = observe(HelmetBodyTracker(), incomplete, helmet)

    return {
        "provenance": "SYNTHETIC TEACHING EXAMPLE - not participant data",
        "units": "m",
        "segment_count": baseline["segment_count"],
        "right_hand_optitrack_m": hand(baseline).tolist(),
        "right_hand_robot_m": hand(baseline, "robot").tolist(),
        "common_translation_hand_error_m": float(np.linalg.norm(hand(translated) - hand(baseline))),
        "head_only_turn_hand_error_m": float(np.linalg.norm(hand(head_turned) - hand(baseline))),
        "first_frame_features_ready": baseline["features_ready"],
        "second_frame_features_ready": moving["features_ready"],
        "second_frame_body_geometry": moving["body_geometry"],
        "rejected_examples": {
            label: {"available": result["available"], "reason": result["reason"]}
            for label, result in (("stale", stale), ("receive_skew", skewed), ("missing_segment", missing))
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="optional synthetic JSON output path")
    args = parser.parse_args()
    report = run_demo()
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
