#!/usr/bin/env python3
"""Move to taught ceiling pose, capture independent validation, return low."""
from __future__ import annotations
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from capture_handeye_pose import capture
from vg10 import VG10

HOST = "192.168.2.101"

def main():
    import rtde_control, rtde_receive
    poses = json.load(open("data/taught_poses.json", encoding="utf-8"))
    low, top = poses["pose1_low"]["q"], poses["pose2_top"]["q"]
    rx = rtde_receive.RTDEReceiveInterface(HOST)
    state = (rx.getRobotMode(), rx.getSafetyMode(), rx.getActualQ())
    rx.disconnect()
    if state[:2] != (7, 1): raise SystemExit(f"bad robot/safety mode {state[:2]}")
    v = VG10().stats().get("stats", {})
    if min(v.get("vacuum_A_permille",0),v.get("vacuum_B_permille",0)) < 500:
        raise SystemExit("vacuum below 500; refusing lift")
    c = rtde_control.RTDEControlInterface(HOST)
    try:
        print("lifting slowly to taught top pose")
        if not c.moveJ(top, .10, .15): raise RuntimeError("top move failed")
        time.sleep(1)
        row={"label":"pose_08_top_validation",**capture(HOST,2,"127.0.0.1",2,3)}
        with open("data/calib/handeye_samples.jsonl","a",encoding="utf-8") as f:
            f.write(json.dumps(row,separators=(",",":"))+"\n")
        print("top captured",row["samples"],"samples; returning low")
        if not c.moveJ(low, .10, .15): raise RuntimeError("return move failed")
        print("returned to taught low pose")
    finally:
        c.stopJ(.5); c.disconnect()
    print(json.dumps(row,indent=2))

if __name__=="__main__":main()
