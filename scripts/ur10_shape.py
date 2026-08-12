"""ur10_shape.py - forward-kinematics shape checker for the real UR10 (CB3).

Computes where each link lands for a given joint vector, so poses can be
chosen for their SHAPE (upper arm angle, elbow height) before any motion.
Standard UR10 DH parameters.
"""
import math

# UR10 (CB3) DH parameters
D1, A2, A3 = 0.1273, -0.612, -0.5723
D4, D5, D6 = 0.163941, 0.1157, 0.0922


def _dh(theta, d, a, alpha):
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return [
        [ct, -st * ca, st * sa, a * ct],
        [st, ct * ca, -ct * sa, a * st],
        [0.0, sa, ca, d],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _mul(m, n):
    return [[sum(m[i][k] * n[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def link_points(q):
    """Base, shoulder, elbow, wrist1, flange xyz for joint vector q (rad)."""
    params = [
        (q[0], D1, 0.0, math.pi / 2),
        (q[1], 0.0, A2, 0.0),
        (q[2], 0.0, A3, 0.0),
        (q[3], D4, 0.0, math.pi / 2),
        (q[4], D5, 0.0, -math.pi / 2),
        (q[5], D6, 0.0, 0.0),
    ]
    t = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    pts = {"base": (0.0, 0.0, 0.0)}
    names = ["shoulder", "elbow", "wrist1", "wrist2", "wrist3", "flange"]
    for name, (th, d, a, al) in zip(names, params):
        t = _mul(t, _dh(th, d, a, al))
        pts[name] = (t[0][3], t[1][3], t[2][3])
    return pts


def shape_report(q):
    """Human-readable shape metrics for a joint vector."""
    p = link_points(q)
    sh, el, w1 = p["shoulder"], p["elbow"], p["wrist1"]
    dx = el[0] - sh[0]
    dy = el[1] - sh[1]
    dz = el[2] - sh[2]
    horiz = math.hypot(dx, dy)
    upper_ang = math.degrees(math.atan2(dz, horiz))  # 0 = horizontal, 90 = up
    return {
        "upper_arm_deg_from_horizontal": round(upper_ang, 1),
        "elbow_z": round(el[2], 3),
        "elbow_xy_reach": round(math.hypot(el[0], el[1]), 3),
        "wrist_z": round(w1[2], 3),
        "flange_z": round(p["flange"][2], 3),
    }
