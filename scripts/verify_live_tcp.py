#!/usr/bin/env python3
"""GROUND-TRUTH VERIFICATION of the P0 live-TCP fix. Real arm required.

Green unit tests prove the wiring. They do NOT prove that this CB3 controller
serves getActualTCPPose, nor that a second RTDE client is accepted alongside
the IO interface and the dashboard connection. CB3 is fussier about concurrent
RTDE clients than e-series, so that is the specific risk being tested here.

WHAT YOU DO:
  1. Power the arm, release brakes. Remote Control is NOT required.
  2. Run this script.
  3. When it says so, put the pendant in FREEDRIVE and move the arm around by
     hand -- ideally the full panel-cycle sweep, low pose up to the top pose.
  4. Watch d change. Ctrl-C or let it time out.

WHAT IT PROVES:
  * the receive interface opens alongside IO + dashboard (the CB3 risk)
  * getActualTCPPose returns a real, moving pose
  * FeatureExtractor.set_tcp actually changes computed separation on hardware
  * a raw evidence log exists afterwards, so the claim is re-checkable

The "operator" here is a fixed virtual point. Nothing needs to be worn and no
Xsens machine needs to be running.

  python scripts/verify_live_tcp.py
  python scripts/verify_live_tcp.py --host 192.168.2.101 --duration 90
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.config import load_config  # noqa: E402
from hrc_safety.features import FeatureExtractor  # noqa: E402

MOVE_THRESHOLD_M = 0.15   # arm must travel at least this far to count as moved
D_THRESHOLD_M = 0.05      # separation must respond by at least this much


def connect(host: str):
    """Open all three clients in the SAME order live_run uses on the real arm."""
    from rtde_io import RTDEIOInterface
    from rtde_receive import RTDEReceiveInterface
    from dashboard_client import DashboardClient

    report = {}
    print(f"connecting to {host} ...")
    io = RTDEIOInterface(host)
    report["rtde_io"] = "ok"
    print("  RTDEIOInterface     ok")

    dash = DashboardClient(host)
    dash.connect()
    report["dashboard"] = "ok"
    print("  DashboardClient     ok")

    # The actual risk: a SECOND rtde client while io + dashboard are already up.
    recv = RTDEReceiveInterface(host)
    report["rtde_receive"] = "ok"
    print("  RTDEReceiveInterface ok  <-- the concurrent-client risk cleared")

    try:
        print("  robotmode:", dash.send("robotmode") if hasattr(dash, "send") else "n/a")
    except Exception:
        pass
    return io, dash, recv, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=None, help="robot IP (default: config)")
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--rate", type=float, default=20.0, help="print/sample Hz")
    ap.add_argument("--operator", default="1.5,0.0,1.0",
                    help="virtual operator point x,y,z in the robot base frame")
    ap.add_argument("--out", default="data/verification/live_tcp_check.jsonl")
    args = ap.parse_args()

    config = load_config()
    host = args.host or config["robot"]["host"]
    operator = [float(v) for v in args.operator.split(",")]
    return run(host, operator, args)


def run(host: str, operator: list[float], args) -> int:
    try:
        io, dash, recv, report = connect(host)
    except Exception as exc:
        print(f"\nFAIL: could not open the interfaces: {type(exc).__name__}: {exc}")
        print("Check: arm powered, ethernet up, Mac on 192.168.1.100, "
              "and nothing else already holding an RTDE client.")
        return 1

    fx = FeatureExtractor(config_tcp(), sample_rate_hz=60.0)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fh = open(args.out, "a")

    print(f"\nvirtual operator fixed at {operator}")
    print("NOW: put the pendant in FREEDRIVE and move the arm through the "
          "panel-cycle sweep by hand.\n")
    print(f"{'t':>6} {'tcp_x':>7} {'tcp_y':>7} {'tcp_z':>7} {'d(m)':>7}")

    tcps, ds = [], []
    dt = 1.0 / args.rate
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < args.duration:
            t = time.monotonic() - t0
            pose = recv.getActualTCPPose()
            if not pose or len(pose) < 3:
                print("  pose unavailable this tick")
                time.sleep(dt)
                continue
            tcp = [float(pose[0]), float(pose[1]), float(pose[2])]
            fx.set_tcp(tcp)
            frame = fx.push(t, operator)
            d = frame.d if frame is not None else float("nan")
            tcps.append(tcp)
            if frame is not None:
                ds.append(d)
            fh.write(json.dumps({"t": round(t, 3), "tcp": tcp,
                                 "operator": operator, "d": d}) + "\n")
            print(f"{t:6.1f} {tcp[0]:7.3f} {tcp[1]:7.3f} {tcp[2]:7.3f} {d:7.3f}")
            time.sleep(dt)
    except KeyboardInterrupt:
        print("\nstopped by user.")
    finally:
        fh.close()
    return verdict(tcps, ds, args.out)


def config_tcp():
    """Deliberately start from the OLD static config value, so the log shows
    the fix taking over from the phantom on the very first tick."""
    return load_config()["scenario"]["tcp_position"]


def verdict(tcps, ds, out_path: str) -> int:
    if len(tcps) < 5 or len(ds) < 5:
        print("\nFAIL: not enough samples. Was the arm powered and reachable?")
        return 1

    span = [max(p[i] for p in tcps) - min(p[i] for p in tcps) for i in range(3)]
    travel = max(span)
    d_span = max(ds) - min(ds)

    print("\n" + "=" * 58)
    print(f"samples            : {len(ds)}")
    print(f"TCP travel x/y/z   : {span[0]:.3f} / {span[1]:.3f} / {span[2]:.3f} m")
    print(f"separation range   : {min(ds):.3f} -> {max(ds):.3f} m  (span {d_span:.3f})")
    print(f"evidence log       : {out_path}")

    if travel < MOVE_THRESHOLD_M:
        print(f"\nINCONCLUSIVE: the arm barely moved ({travel:.3f} m). Re-run and "
              f"freedrive it through a real sweep.")
        return 2
    if d_span < D_THRESHOLD_M:
        print(f"\nFAIL: the arm moved {travel:.3f} m but separation only changed "
              f"{d_span:.3f} m. The extractor is STILL measuring to a phantom.")
        return 1

    print("\nPASS: the arm moved and computed separation tracked it.")
    print("P0 verified on real hardware. Live separation is no longer a phantom.")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
