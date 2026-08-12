"""Level the cups at King's taught pose 1: same xyz, orientation -> flat up.

Small wrist-only correction (~4 deg). IK seeded at the taught joints so the
arm shape stays as taught. Aborts if IK's answer strays far from taught.
"""
import json
import math
import sys
import time
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

with open("data/taught_poses.json") as f:
    taught = json.load(f)["pose1_low"]
q0, tcp = taught["q"], taught["tcp"]

level = [tcp[0], tcp[1], tcp[2], 0.0, 0.0, 0.0]
ql = pt.ik(level, q0)
if not ql:
    sys.exit("ABORT: no IK answer.")
dmax = math.degrees(max(abs(a - b) for a, b in zip(ql, q0)))
print("correction per joint (deg):",
      [round(math.degrees(a - b), 2) for a, b in zip(ql, q0)])
if dmax > 12.0:
    sys.exit(f"ABORT: correction too large ({dmax:.1f} deg) - not a trim.")

pt.goto_j(ql, v=0.05)
time.sleep(1.0)
for _ in range(30):
    n = pt.snap()
    if math.degrees(max(abs(a - b) for a, b in zip(n["q"], ql))) < 0.3:
        break
    time.sleep(1.0)
n = pt.snap()
tilt = math.degrees(math.hypot(n["tcp"][3], n["tcp"][4]))
print("final tcp:", [round(v, 4) for v in n["tcp"]], f"| tilt: {tilt:.2f} deg")
with open("data/taught_poses.json", "w") as f:
    json.dump({"pose1_low": n, "tilt_deg": round(tilt, 2)}, f, indent=2)
print("pose 1 updated -> data/taught_poses.json")
