"""Snapshot current taught pose (freedriven by King) and save as pose 1."""
import json
import math
import sys
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

n = pt.snap()
q_deg = [round(math.degrees(v), 2) for v in n["q"]]
tcp = n["tcp"]
tilt = math.degrees(math.hypot(tcp[3], tcp[4]))
print("POSE 1 joints (deg):", q_deg)
print("POSE 1 tcp        :", [round(v, 4) for v in tcp])
print(f"cup tilt from level: {tilt:.1f} deg")
with open("data/taught_poses.json", "w") as f:
    json.dump({"pose1_low": n, "tilt_deg": round(tilt, 2)}, f, indent=2)
print("saved -> data/taught_poses.json")
