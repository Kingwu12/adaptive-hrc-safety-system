"""Recover from singular top: unlock pstop, movej out of singularity to
z=1.45 (joint move - singularity-safe), then movel down to pose 1."""
import json
import math
import sys
import time
import urllib.request
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

req = urllib.request.Request(
    "http://127.0.0.1:8765/api/robot",
    data=json.dumps({"action": "unlock"}).encode(),
    headers={"Content-Type": "application/json"})
print("unlock:", urllib.request.urlopen(req, timeout=8).read().decode())
time.sleep(2)

with open("data/taught_poses.json") as f:
    d = json.load(f)
p1 = d["pose1_low"]
x, y = p1["tcp"][0], p1["tcp"][1]

n = pt.snap()
q145 = pt.ik([x, y, 1.45, 0.0, 0.0, 0.0], n["q"])
if not q145:
    sys.exit("ABORT: no IK for z=1.45")
print("escape target (deg):", [round(math.degrees(v), 1) for v in q145])
qs = "[" + ",".join(f"{v:.6f}" for v in q145) + "]"
body = [
    f"movej({qs}, a=0.4, v=0.2)",
    f"movel(p[{x:.5f},{y:.5f},{p1['tcp'][2]:.5f},0,0,0], a=0.4, v=0.25)",
]
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
d["pose2_top"] = {"tcp": [x, y, 1.45, 0.0, 0.0, 0.0],
                  "q": [round(v, 6) for v in q145]}
with open("data/taught_poses.json", "w") as f:
    json.dump(d, f, indent=2)
print("pose 2 = z 1.45 (joints recorded); arm returning to pose 1.")
