#!/usr/bin/env python3
"""Record the raw mocap stream to append-only JSONL (pre-filtering).

One line per 60 Hz tick: {"t":..., "pos":[x,y,z], "stale":..., "age_s":...,
"motive_timestamp":...}. Every pilot session becomes replayable offline
through ALL rungs, and is the labelled-data source for fit_transitions.

Requires Motive's NatNetClient.py vendored at src/hrc_safety/mocap/vendor/
(ships with the Motive SDK samples on the lab machine).

  python scripts/record_mocap.py --out data/mocap/pilot01.jsonl \
      --rigid-body 1 [--extrinsics configs/mocap_extrinsics.yaml]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.config import load_config  # noqa: E402
from hrc_safety.mocap import MocapBridge, load_extrinsics  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="output JSONL path")
    ap.add_argument("--rigid-body", type=int, default=1,
                    help="Motive streaming ID of the torso rigid body")
    ap.add_argument("--extrinsics", default=None,
                    help="configs/mocap_extrinsics.yaml (omit = mocap frame)")
    ap.add_argument("--server", default="127.0.0.1", help="Motive host IP")
    ap.add_argument("--client", default="127.0.0.1", help="this machine's IP")
    args = ap.parse_args()

    try:
        from hrc_safety.mocap.vendor.NatNetClient import NatNetClient  # noqa
    except ImportError:
        print("NatNetClient.py not vendored yet: copy it from the Motive SDK "
              "samples into src/hrc_safety/mocap/vendor/ (lab machine).")
        return 2

    cfg = load_config(os.path.join(os.path.dirname(__file__), "..",
                                   "configs", "default.yaml"))
    ext = load_extrinsics(args.extrinsics) if args.extrinsics else None
    bridge = MocapBridge(sample_rate_hz=cfg.features.sample_rate_hz,
                         extrinsics=ext)

    def on_rb(rb_id: int, pos, rot) -> None:  # NatNet callback signature
        if rb_id == args.rigid_body:
            bridge.on_sample(time.time(), pos, tracked=True,
                             wall_time=time.monotonic())

    client = NatNetClient()
    client.set_server_address(args.server)
    client.set_client_address(args.client)
    client.rigid_body_listener = on_rb
    client.run()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    dt = 1.0 / cfg.features.sample_rate_hz
    print(f"recording -> {args.out}  (Ctrl-C to stop)")
    with open(args.out, "a") as fh:
        try:
            while True:
                s = bridge.tick(time.monotonic())
                if s is not None:
                    fh.write(json.dumps({
                        "t": round(s.t, 6), "pos": s.position.tolist(),
                        "stale": s.stale, "age_s": round(s.age_s, 4),
                        "motive_timestamp": s.motive_timestamp}) + "\n")
                time.sleep(dt)
        except KeyboardInterrupt:
            print("stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
