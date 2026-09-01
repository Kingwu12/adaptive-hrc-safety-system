#!/usr/bin/env python3
"""Capture one stationary UR TCP + OptiTrack PANEL/ROBOT_BASE hand-eye pose."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from hrc_safety.mocap.optitrack_transport import parse_natnet4_frame  # noqa: E402


def _mean_quaternion_xyzw(values):
    q = np.asarray(values, float)
    q[q[:, 3] < 0] *= -1
    return Rotation.from_quat(q).mean().as_quat()


def capture(host: str, seconds: float, local_ip: str,
            panel_id: int, base_id: int) -> dict:
    import rtde_receive
    rtde = rtde_receive.RTDEReceiveInterface(host)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 1511))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                    socket.inet_aton("239.255.42.99") + socket.inet_aton(local_ip))
    sock.settimeout(0.5)
    rows = []
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            frame = parse_natnet4_frame(data)
            if frame is None:
                continue
            bodies = {b[0]: b for b in frame[1] if b[4]}
            if panel_id not in bodies or base_id not in bodies:
                continue
            tcp = rtde.getActualTCPPose()
            speed = rtde.getActualTCPSpeed()
            if np.linalg.norm(speed) > 0.002:
                raise RuntimeError("robot moved during calibration capture")
            panel, base = bodies[panel_id], bodies[base_id]
            rows.append((tcp, panel[1], panel[2], base[1], base[2],
                         panel[3], base[3], frame[0]))
    finally:
        sock.close(); rtde.disconnect()
    if len(rows) < 30:
        raise RuntimeError(f"only {len(rows)} synchronized samples; tracking unavailable")
    tcp = np.asarray([r[0] for r in rows])
    return {
        "captured_at_unix_s": time.time(), "samples": len(rows),
        "natnet_frame_first_last": [rows[0][7], rows[-1][7]],
        "ur_tcp_xyz_m": tcp[:, :3].mean(0).tolist(),
        "ur_tcp_rotvec_rad": Rotation.from_rotvec(tcp[:, 3:]).mean().as_rotvec().tolist(),
        "panel_xyz_m": np.mean([r[1] for r in rows], axis=0).tolist(),
        "panel_quat_xyzw": _mean_quaternion_xyzw([r[2] for r in rows]).tolist(),
        "robot_base_asset_xyz_m": np.mean([r[3] for r in rows], axis=0).tolist(),
        "robot_base_asset_quat_xyzw": _mean_quaternion_xyzw([r[4] for r in rows]).tolist(),
        "panel_mean_error_mm": float(1000*np.mean([r[5] for r in rows])),
        "base_mean_error_mm": float(1000*np.mean([r[6] for r in rows])),
        "tcp_position_range_mm": (1000*np.ptp(tcp[:, :3], axis=0)).tolist(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", default="data/calib/handeye_samples.jsonl")
    ap.add_argument("--host", default="192.168.2.101")
    ap.add_argument("--local-ip", default="127.0.0.1")
    ap.add_argument("--panel-id", type=int, default=2)
    ap.add_argument("--base-id", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=2.0)
    args = ap.parse_args()
    row = {"label": args.label, **capture(args.host, args.seconds, args.local_ip,
                                           args.panel_id, args.base_id)}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()
