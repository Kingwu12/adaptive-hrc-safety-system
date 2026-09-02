#!/usr/bin/env python3
"""Record the raw Xsens mocap stream to append-only JSONL (pre-filtering).

One line per 60 Hz tick contains the selected segment's compatibility fields
plus ``xsens_frame``: every segment position, every quaternion, packet
counters and timestamps. ``motive_timestamp`` is kept for replay compatibility
and carries the MVN time code in seconds. Sessions replay offline through ALL
rungs and feed fit_transitions labelling.

MVN Analyze setup: Options -> Network Streamer -> UDP, "Position +
Quaternion" datagram, target = this machine : 9763.

  python scripts/record_mocap.py --out data/mocap/pilot01.jsonl \
      [--segment 1] [--port 9763] [--extrinsics configs/mocap_extrinsics.yaml]
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
from hrc_safety.mocap.xsens_transport import (  # noqa: E402
    MVN_FULL_BODY_SEGMENTS, PELVIS, XsensListener)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="output JSONL path")
    ap.add_argument("--segment", type=int, default=PELVIS,
                    help="MVN segment ID to track (1 = pelvis)")
    ap.add_argument("--port", type=int, default=9763, help="UDP listen port")
    ap.add_argument("--extrinsics", default=None,
                    help="configs/mocap_extrinsics.yaml (omit = mocap frame)")
    args = ap.parse_args()

    cfg = load_config(os.path.join(os.path.dirname(__file__), "..",
                                   "configs", "default.yaml"))
    ext = load_extrinsics(args.extrinsics) if args.extrinsics else None
    bridge = MocapBridge(sample_rate_hz=cfg.features.sample_rate_hz,
                         extrinsics=ext)
    listener = XsensListener(bridge, port=args.port, segment_id=args.segment)
    listener.start()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    dt = 1.0 / cfg.features.sample_rate_hz
    print(f"listening on udp:{args.port} -> {args.out}  (Ctrl-C to stop)")
    last_incomplete_count = None
    with open(args.out, "a") as fh:
        try:
            while True:
                s = bridge.tick(time.monotonic())
                if s is not None:
                    frame = listener.latest_frame()
                    segment_count = (0 if frame is None else
                                     len(frame["segments"]))
                    if segment_count < MVN_FULL_BODY_SEGMENTS:
                        if segment_count != last_incomplete_count:
                            print(
                                "NOT RECORDING: incomplete Xsens stream "
                                f"({segment_count}/{MVN_FULL_BODY_SEGMENTS} "
                                "body segments). Check MVN Position + "
                                "Quaternion output."
                            )
                            last_incomplete_count = segment_count
                        time.sleep(dt)
                        continue
                    fh.write(json.dumps({
                        "schema_version": 2,
                        "t": round(s.t, 6), "pos": list(map(float, s.position)),
                        "stale": s.stale, "age_s": round(s.age_s, 4),
                        "motive_timestamp": s.motive_timestamp,
                        "xsens_frame": frame}) + "\n")
                time.sleep(dt)
        except KeyboardInterrupt:
            print("stopped.")
        finally:
            listener.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
