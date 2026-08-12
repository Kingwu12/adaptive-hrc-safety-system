"""Drive to the low loading pose - FK-verified on the robot before motion.

Candidate from shape search: upper arm 30 deg above horizontal, elbow out
over the table, wrist low, cups up at ~0.34 m, reach ~0.91 m.
Aborts (no motion) unless the robot's own FK confirms cups-level.
"""
import math
import sys
import time
sys.path.insert(0, "scripts")
import pose_teach_helper as pt

CAND_DEG = [-90.0, -150.0, -60.0, 120.0, 90.0, 0.0]
q = [math.radians(v) for v in CAND_DEG]
qs = "[" + ",".join(f"{v:.6f}" for v in q) + "]"

out = pt.ask_robot([
    f"p = get_forward_kin({qs})",
    'socket_open("192.168.1.100", 30999, "rb")',
    'socket_send_string(to_str(p), "rb")',
    'socket_close("rb")',
])
print("robot FK says:", out.strip())
if "p[" not in out:
    sys.exit("ABORT: no FK readback - not moving.")
vals = [float(x) for x in out[out.index("[") + 1:out.index("]")].split(",")]
x, y, z, rx, ry, rz = vals
tilt = math.hypot(rx, ry)
print(f"cup pos ({x:.3f},{y:.3f},{z:.3f})  tilt from level: {math.degrees(tilt):.1f} deg")
if math.degrees(tilt) > 3.0:
    sys.exit("ABORT: cups would not be level - not moving.")

print("driving (slow)...")
pt.goto_j(q, v=0.15)
time.sleep(1.0)
for _ in range(40):
    n = pt.snap()
    err = max(abs(a - b) for a, b in zip(n["q"], q))
    if math.degrees(err) < 0.5:
        break
    time.sleep(1.5)
n = pt.snap()
print("final q deg:", [round(math.degrees(v), 1) for v in n["q"]])
print("final tcp  :", [round(v, 3) for v in n["tcp"]])
