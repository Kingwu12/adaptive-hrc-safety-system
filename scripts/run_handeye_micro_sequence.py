#!/usr/bin/env python3
"""Run low-pose micro rotations and capture synchronized hand-eye samples."""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from capture_handeye_pose import capture  # noqa: E402
from vg10 import VG10  # noqa: E402


HOST = "192.168.1.101"
OUT = "data/calib/handeye_samples.jsonl"


def main():
    import rtde_control
    import rtde_receive
    rx = rtde_receive.RTDEReceiveInterface(HOST)
    q0 = rx.getActualQ()
    if rx.getSafetyMode() != 1 or rx.getRobotMode() != 7:
        raise SystemExit("robot is not RUNNING/NORMAL")
    rx.disconnect()
    vac = VG10().stats().get("stats", {})
    if min(vac.get("vacuum_A_permille", 0), vac.get("vacuum_B_permille", 0)) < 500:
        raise SystemExit("vacuum below 500 permille; refusing calibration motion")

    offsets = [(3, .04), (3, -.04), (4, .04), (4, -.04), (5, .04), (5, -.04)]
    control = rtde_control.RTDEControlInterface(HOST)
    try:
        for number, (joint, delta) in enumerate(offsets, start=2):
            target = list(q0); target[joint] += delta
            if not control.moveJ(target, 0.08, 0.10):
                raise RuntimeError(f"move to pose {number} failed")
            time.sleep(.5)
            row = {"label": f"pose_{number:02d}",
                   **capture(HOST, 1.5, "127.0.0.1", 2, 3)}
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            print(row["label"], "captured", row["samples"], "samples")
        control.moveJ(q0, 0.08, 0.10)
    finally:
        control.stopJ(0.5)
        control.disconnect()
    print("returned to start pose")


if __name__ == "__main__": main()
