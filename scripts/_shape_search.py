"""Shape search v2: both wrist families, realistic bounds."""
import math
import sys
sys.path.insert(0, "scripts")
import ur10_shape

best = []
for q4d, ssum in ((270.0, -270.0), (90.0, -90.0)):
    for q1d in range(-230, -99, 5):           # upper arm low-to-mid, reach side
        for q2d in range(-150, 151, 5):
            q3d = ssum - q1d - q2d
            if abs(q3d) > 155:
                continue
            q = [math.radians(v) for v in [-90.0, q1d, q2d, q3d, q4d, 0.0]]
            rep = ur10_shape.shape_report(q)
            if not (5 < rep["upper_arm_deg_from_horizontal"] < 45):
                continue
            pts = ur10_shape.link_points(q)
            el, w1, fl = pts["elbow"], pts["wrist1"], pts["flange"]
            if el[1] > -0.3:
                continue
            cup_z = fl[2] + 0.105
            if el[2] < 0.10 or w1[2] < 0.12 or fl[2] < 0.12:
                continue
            if cup_z < 0.22 or cup_z > 0.55:
                continue
            if -fl[1] < 0.30 or -fl[1] > 0.95:
                continue
            best.append((round(cup_z, 3), int(q4d), q1d, q2d, round(q3d, 1),
                         round(-fl[1], 3), round(fl[0], 3),
                         round(el[2], 2), round(w1[2], 2)))
best.sort()
print("cup_z | fam q1 q2 q3 | reach_y x | elbow_z wrist_z")
for b in best[:10]:
    print(b)
print("total:", len(best))
