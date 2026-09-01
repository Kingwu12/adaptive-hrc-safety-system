#!/usr/bin/env python3
"""Solve OptiTrack-world -> UR-base and TCP -> PANEL transforms."""
from __future__ import annotations

import argparse
import json
import numpy as np
import yaml
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def T(xyz, rotation, quaternion=False):
    m = np.eye(4); m[:3, 3] = xyz
    m[:3, :3] = Rotation.from_quat(rotation).as_matrix() if quaternion else Rotation.from_rotvec(rotation).as_matrix()
    return m


def from_params(p):
    return T(p[:3], p[3:])


def residual(p, rows):
    world_from_ur = from_params(p[:6]); tcp_from_panel = from_params(p[6:])
    out = []
    for r in rows:
        world_from_panel = T(r["panel_xyz_m"], r["panel_quat_xyzw"], True)
        ur_from_tcp = T(r["ur_tcp_xyz_m"], r["ur_tcp_rotvec_rad"])
        delta = np.linalg.inv(world_from_panel) @ world_from_ur @ ur_from_tcp @ tcp_from_panel
        out.extend(delta[:3, 3] * 10.0)  # balance metres with radians
        out.extend(Rotation.from_matrix(delta[:3, :3]).as_rotvec())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--infile", default="data/calib/handeye_samples.jsonl")
    ap.add_argument("--out", default="configs/mocap_extrinsics.yaml")
    ap.add_argument("--validation-position-mm", type=float)
    ap.add_argument("--validation-orientation-deg", type=float)
    args = ap.parse_args()
    rows = [json.loads(x) for x in open(args.infile, encoding="utf-8") if x.strip()]
    if len(rows) < 5:
        raise SystemExit("need at least 5 varied poses")
    p = least_squares(residual, np.zeros(12), args=(rows,), max_nfev=5000).x
    world_from_ur = from_params(p[:6]); ur_from_world = np.linalg.inv(world_from_ur)
    errors = np.asarray(residual(p, rows)).reshape(-1, 6)
    position_mm = np.linalg.norm(errors[:, :3] / 10.0, axis=1) * 1000
    validation_ok = (args.validation_position_mm is not None and
                     args.validation_orientation_deg is not None and
                     args.validation_position_mm <= 20.0 and
                     args.validation_orientation_deg <= 2.0 and
                     float(position_mm.max()) <= 5.0)
    doc = {
        "rotation": ur_from_world[:3, :3].tolist(),
        "translation": ur_from_world[:3, 3].tolist(),
        "tcp_from_panel_rotation": from_params(p[6:])[:3, :3].tolist(),
        "tcp_from_panel_translation": from_params(p[6:])[:3, 3].tolist(),
        "calibration": {"poses": len(rows), "position_residuals_mm": position_mm.tolist(),
                        "rmse_mm": float(np.sqrt(np.mean(position_mm**2))),
                        "max_mm": float(position_mm.max()),
                        "independent_validation_position_mm": args.validation_position_mm,
                        "independent_validation_orientation_deg": args.validation_orientation_deg,
                        "acceptance_limits": {"position_mm": 20.0, "orientation_deg": 2.0,
                                              "fit_max_mm": 5.0},
                        "accepted": validation_ok},
    }
    with open(args.out, "w", encoding="utf-8") as fh: yaml.safe_dump(doc, fh, sort_keys=False)
    print(yaml.safe_dump(doc, sort_keys=False))


if __name__ == "__main__": main()
