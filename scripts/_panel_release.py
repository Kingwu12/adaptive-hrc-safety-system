"""Release sequence: lower panel to pose 1, THEN cut suction. Never drop
from height."""
import json
import math
import sys
import time
import urllib.request
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

with open("data/taught_poses.json") as f:
    d = json.load(f)
p1 = d["pose1_low"]
x, y, z1 = p1["tcp"][0], p1["tcp"][1], p1["tcp"][2]

pt.PAYLOAD = "set_payload(3.2,[0,0,0.10])"
body = [f"movel(p[{x:.5f},{y:.5f},{z1:.5f},0,0,0], a=0.3, v=0.2)"]
print("lowering panel to pose 1...")
pt.ask_robot(body, timeout=2.0)
time.sleep(1.0)
last = None
for _ in range(60):
    n = pt.snap()
    z = n["tcp"][2]
    if last is not None and abs(z - last) < 0.0005 and abs(z - z1) < 0.01:
        break
    last = z
    time.sleep(1.0)
n = pt.snap()
print("down at:", [round(v, 3) for v in n["tcp"]])
if abs(n["tcp"][2] - z1) > 0.02:
    sys.exit("ABORT: did not reach pose 1 - NOT releasing at height.")

req = urllib.request.Request(
    "http://127.0.0.1:8765/api/gripper",
    data=json.dumps({"action": "release", "channel": "BOTH"}).encode(),
    headers={"Content-Type": "application/json"})
print("release:", urllib.request.urlopen(req, timeout=10).read().decode())
print("panel released at pose 1. cycle complete.")
