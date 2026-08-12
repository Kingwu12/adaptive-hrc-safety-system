"""Debug: how close does each constraint get? Print least-bad candidates."""
import math
import sys
sys.path.insert(0, "scripts")
import ur10_shape

rows = []
for q1d in range(-360, 1, 5):
    for q2d in range(-150, 151, 5):
        q3d = -270.0 - q1d - q2d
        if abs(q3d) > 155:
            continue
        q = [math.radians(v) for v in [-90.0, q1d, q2d, q3d, 270.0, 0.0]]
        rep = ur10_shape.shape_report(q)
        if abs(rep["upper_arm_deg_from_horizontal"]) > 20:
            continue
        pts = ur10_shape.link_points(q)
        el, w1, fl = pts["elbow"], pts["wrist1"], pts["flange"]
        rows.append((q1d, q2d, round(q3d, 1),
                     round(rep["upper_arm_deg_from_horizontal"], 1),
                     [round(v, 2) for v in el],
                     [round(v, 2) for v in w1],
                     [round(v, 2) for v in fl]))
print("total horiz-upper-arm candidates:", len(rows))
print("q1 q2 q3 | upper_deg | elbow xyz | wrist1 xyz | flange xyz")
for r in rows[:14]:
    print(r)
