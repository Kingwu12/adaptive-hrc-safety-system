#!/usr/bin/env python3
"""Solve the mocap -> robot-base rigid transform (Kabsch) and measure Sa.

Mode 1 (extrinsics): paired points -> configs/mocap_extrinsics.yaml
  Touch the robot TCP to 3-4 taped floor points (poses from the controller),
  read the same points with a marker wand (from Motive), put both in a YAML:
    pairs:
      - {robot: [x,y,z], mocap: [x,y,z]}
      ...
  python scripts/calibrate_mocap.py extrinsics --pairs data/calib/pairs.yaml

Mode 2 (sa): stillness recording -> Sa estimate (p99 residual magnitude)
  python scripts/calibrate_mocap.py sa --log data/mocap/still01.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

OUT = os.path.join(os.path.dirname(__file__), "..", "configs",
                   "mocap_extrinsics.yaml")


def kabsch(mocap: np.ndarray, robot: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rigid (R, t) minimising ||R@mocap_i + t - robot_i|| (SVD, det-corrected)."""
    cm, cr = mocap.mean(axis=0), robot.mean(axis=0)
    H = (mocap - cm).T @ (robot - cr)
    U, _, Vt = np.linalg.svd(H)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
    R = Vt.T @ D @ U.T
    return R, cr - R @ cm


def cmd_extrinsics(pairs_path: str) -> int:
    with open(pairs_path) as fh:
        pairs = yaml.safe_load(fh)["pairs"]
    if len(pairs) < 3:
        print("need >= 3 point pairs"); return 2
    mocap = np.array([p["mocap"] for p in pairs], float)
    robot = np.array([p["robot"] for p in pairs], float)
    R, t = kabsch(mocap, robot)
    resid = np.linalg.norm((mocap @ R.T + t) - robot, axis=1)
    with open(OUT, "w") as fh:
        yaml.safe_dump({"rotation": R.tolist(), "translation": t.tolist(),
                        "fit_residuals_m": [round(float(r), 5) for r in resid],
                        "source_pairs": pairs_path}, fh, sort_keys=False)
    print(f"wrote {OUT}  max residual {resid.max()*1000:.1f} mm "
          f"({'OK' if resid.max() < 0.02 else 'HIGH - re-measure'})")
    return 0


def cmd_sa(log_path: str) -> int:
    pos = np.array([json.loads(l)["pos"] for l in open(log_path)
                    if l.strip()], float)
    if len(pos) < 60:
        print("need >= 1 s of stillness data"); return 2
    resid = np.linalg.norm(pos - pos.mean(axis=0), axis=1)
    print(f"n={len(pos)}  p50={np.percentile(resid,50)*1000:.1f} mm  "
          f"p99={np.percentile(resid,99)*1000:.1f} mm")
    print(f"Sa (p99, use in configs/default.yaml envelope.Sa): "
          f"{np.percentile(resid,99):.4f} m")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)
    e = sub.add_parser("extrinsics"); e.add_argument("--pairs", required=True)
    s = sub.add_parser("sa"); s.add_argument("--log", required=True)
    a = ap.parse_args()
    return cmd_extrinsics(a.pairs) if a.mode == "extrinsics" else cmd_sa(a.log)


if __name__ == "__main__":
    raise SystemExit(main())
