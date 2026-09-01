#!/usr/bin/env python3
"""One validated low -> ceiling -> low hardware check; no release."""
from __future__ import annotations

import json

from capture_handeye_pose import capture
from vg10 import VG10

HOST = "192.168.1.101"


def vacuum() -> tuple[int, int]:
    stats = VG10().stats().get("stats", {})
    return (int(stats.get("vacuum_A_permille", 0)),
            int(stats.get("vacuum_B_permille", 0)))


def main() -> None:
    import rtde_control
    import rtde_receive

    poses = json.load(open("data/taught_poses.json", encoding="utf-8"))
    low = poses["pose1_low"]["q"]
    top = poses["pose2_top"]["q"]
    rx = rtde_receive.RTDEReceiveInterface(HOST)
    mode = (rx.getRobotMode(), rx.getSafetyMode())
    rx.disconnect()
    if mode != (7, 1):
        raise SystemExit(f"robot not ready: robot/safety modes {mode}")
    before = vacuum()
    if min(before) < 500:
        raise SystemExit(f"vacuum below lift threshold: {before}")

    control = rtde_control.RTDEControlInterface(HOST)
    result: dict = {"vacuum_before": before}
    try:
        print("MOTION: low -> taught ceiling")
        if not control.moveJ(top, 0.10, 0.15):
            raise RuntimeError("ceiling move failed")
        result["top_tracking"] = capture(HOST, 2, "127.0.0.1", 2, 3)
        result["vacuum_top"] = vacuum()
        if min(result["vacuum_top"]) < 500:
            raise RuntimeError(f"vacuum degraded at ceiling: {result['vacuum_top']}")
        print("MOTION: taught ceiling -> low")
        if not control.moveJ(low, 0.10, 0.15):
            raise RuntimeError("return move failed")
        result["vacuum_after"] = vacuum()
    finally:
        control.stopJ(0.5)
        control.disconnect()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
