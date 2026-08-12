"""Lock pose 2 at z=1.45 and return to pose 1 for panel loading."""
import json
import math
import sys
import time
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

with open("data/taught_poses.json") as f:
    d = json.load(f)
p1 = d["pose1_low"]
x, y = p1["tcp"][0], p1["tcp"][1]
TOP_Z = 1.45

# settle exactly at the locked top, then descend to pose 1
body = [
    f"movel(p[{x:.5f},{y:.5f},{TOP_Z:.5f},0,0,0], a=0.4, v=0.15)",
    f"movel(p[{x:.5f},{y:.5f},{p1['tcp'][2]:.5f},0,0,0], a=0.4, v=0.25)",
]
print("settling at top, then descending to pose 1...")
pt.ask_robot(body, timeout=2.0)
time.sleep(1.0)
last = None
for _ in range(60):
    n = pt.snap()
    z = n["tcp"][2]
    if last is not None and abs(z - last) < 0.0005 and abs(z - p1["tcp"][2]) < 0.01:
        break
    last = z
    time.sleep(1.0)
n = pt.snap()
print("now at:", [round(v, 4) for v in n["tcp"]])

top = {"q": None, "tcp": [x, y, TOP_Z, 0.0, 0.0, 0.0]}
d["pose2_top"] = top
d.pop("pose2_top_draft", None)
with open("data/taught_poses.json", "w") as f:
    json.dump(d, f, indent=2)
print("pose 2 locked at z=1.45; back at pose 1 for loading.")
