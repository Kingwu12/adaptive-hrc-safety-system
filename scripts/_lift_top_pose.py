"""Vertical lift to draft TOP pose: linear rise from pose 1, cups level.

Target: cup face ~1.15 m above base (~1.9 m above floor given King's
"max ~2.1 m" estimate). Trim afterwards by eye. movel = straight line,
no arm-shape surprises.
"""
import json
import math
import sys
import time
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

with open("data/taught_poses.json") as f:
    p1 = json.load(f)["pose1_low"]
x, y = p1["tcp"][0], p1["tcp"][1]
TARGET_Z = 1.15

body = [f"movel(p[{x:.5f},{y:.5f},{TARGET_Z:.5f},0,0,0], a=0.2, v=0.1)"]
print(f"lifting to z={TARGET_Z} (x={x:.3f}, y={y:.3f})...")
pt.ask_robot(body, timeout=2.0)
time.sleep(1.0)
last = None
for _ in range(60):
    n = pt.snap()
    z = n["tcp"][2]
    if last is not None and abs(z - last) < 0.0005 and abs(z - TARGET_Z) < 0.01:
        break
    last = z
    time.sleep(1.0)
n = pt.snap()
tilt = math.degrees(math.hypot(n["tcp"][3], n["tcp"][4]))
print("final tcp:", [round(v, 4) for v in n["tcp"]], f"| tilt {tilt:.2f} deg")
print("final q  :", [round(math.degrees(v), 1) for v in n["q"]])
data = {"pose1_low": p1, "pose2_top_draft": n}
with open("data/taught_poses.json", "w") as f:
    json.dump(data, f, indent=2)
print("draft top pose saved.")
