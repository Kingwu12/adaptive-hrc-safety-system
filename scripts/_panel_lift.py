"""Panel lift: verify vacuum seal, then rise to pose 2 (z=1.45) and hold."""
import json
import math
import sys
import time
import urllib.request
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

stats = json.loads(urllib.request.urlopen(
    "http://127.0.0.1:8765/api/rig", timeout=8).read())["gripper"]
va, vb = stats["vacuum_A_permille"], stats["vacuum_B_permille"]
print(f"vacuum A={va} B={vb} (permille), pump={stats['pump_rpm']} rpm")
if min(va, vb) < 350:
    sys.exit("ABORT: no proper seal on both channels - press the panel down "
             "flat and rerun.")

with open("data/taught_poses.json") as f:
    d = json.load(f)
x, y = d["pose1_low"]["tcp"][0], d["pose1_low"]["tcp"][1]

# panel aboard: heavier payload so the safety system expects the mass
pt.PAYLOAD = "set_payload(3.2,[0,0,0.10])"
body = [f"movel(p[{x:.5f},{y:.5f},1.45000,0,0,0], a=0.3, v=0.25)"]
print("lifting panel to pose 2...")
pt.ask_robot(body, timeout=2.0)
time.sleep(1.0)
last = None
for _ in range(60):
    n = pt.snap()
    z = n["tcp"][2]
    if last is not None and abs(z - last) < 0.0005 and abs(z - 1.45) < 0.01:
        break
    last = z
    time.sleep(1.0)
n = pt.snap()
s2 = json.loads(urllib.request.urlopen(
    "http://127.0.0.1:8765/api/rig", timeout=8).read())["gripper"]
print("at:", [round(v, 3) for v in n["tcp"]],
      f"| vacuum A={s2['vacuum_A_permille']} B={s2['vacuum_B_permille']}")
print("HOLDING at pose 2.")
