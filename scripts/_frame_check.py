"""Frame calibration: compare FK against the robot's actual TCP."""
import math
import sys
sys.path.insert(0, "scripts")
import ur10_shape
import rtde_receive

r = rtde_receive.RTDEReceiveInterface("192.168.2.101")
q = r.getActualQ()
tcp = r.getActualTCPPose()
pts = ur10_shape.link_points(q)
print("actual q deg:", [round(math.degrees(v), 1) for v in q])
print("actual TCP  :", [round(v, 3) for v in tcp[:3]])
print("FK flange   :", [round(v, 3) for v in pts["flange"]])
print("FK elbow    :", [round(v, 3) for v in pts["elbow"]])
print("FK wrist1   :", [round(v, 3) for v in pts["wrist1"]])
