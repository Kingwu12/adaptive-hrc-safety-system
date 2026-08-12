"""Trim top pose +40 cm, quicker lift."""
import json
import math
import sys
import time
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

with open("data/taught_poses.json") as f:
    d = json.load(f)
x, y = d["pose2_top_draft"]["tcp"][0], d["pose2_top_draft"]["tcp"][1]
TARGET_Z = 1.55

body = [f"movel(p[{x:.5f},{y:.5f},{TARGET_Z:.5f},0,0,0], a=0.4, v=0.25)"]
print(f"rising to z={TARGET_Z}...")
pt.ask_robot(body, timeout=2.0)
time.sleep(1.0)
last = None
for _ in range(40):
    n = pt.snap()
    z = n["tcp"][2]
    if last is not None and abs(z - last) < 0.0005:
        break
    last = z
    time.sleep(1.0)
n = pt.snap()
print("final tcp:", [round(v, 4) for v in n["tcp"]])
print("final q  :", [round(math.degrees(v), 1) for v in n["q"]])
d["pose2_top_draft"] = n
with open("data/taught_poses.json", "w") as f:
    json.dump(d, f, indent=2)
