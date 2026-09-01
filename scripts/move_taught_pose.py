#!/usr/bin/env python3
"""Move the UR10e slowly to one validated taught pose with grip interlock."""
from __future__ import annotations

import argparse
import json

from vg10 import VG10

HOST = "192.168.1.101"


def main() -> None:
    import rtde_control
    import rtde_receive

    ap = argparse.ArgumentParser()
    ap.add_argument("pose", choices=("low", "top"))
    args = ap.parse_args()
    poses = json.load(open("data/taught_poses.json", encoding="utf-8"))
    target = poses["pose1_low" if args.pose == "low" else "pose2_top"]["q"]
    rx = rtde_receive.RTDEReceiveInterface(HOST)
    mode = (rx.getRobotMode(), rx.getSafetyMode())
    rx.disconnect()
    if mode != (7, 1):
        raise SystemExit(f"robot not ready: robot/safety modes {mode}")
    stats = VG10().stats().get("stats", {})
    vacuum = (int(stats.get("vacuum_A_permille", 0)),
              int(stats.get("vacuum_B_permille", 0)))
    if min(vacuum) < 500:
        raise SystemExit(f"vacuum below motion threshold: {vacuum}")
    control = rtde_control.RTDEControlInterface(HOST)
    try:
        if not control.moveJ(target, 0.10, 0.15):
            raise RuntimeError(f"move to {args.pose} failed")
    finally:
        control.stopJ(0.5)
        control.disconnect()
    print(json.dumps({"ok": True, "pose": args.pose, "vacuum": vacuum}))


if __name__ == "__main__":
    main()
