#!/usr/bin/env python3
"""Replay a logged controller run onto URSim (or a real UR10e) in real time.

Demo for the three-rung comparison: run run_simulation.py first (it writes
data/logs/{fixed_zone,dynamic_ssm,adaptive}.jsonl), then replay any log here
and watch the speed slider + protective stops act on the virtual pendant.

  python scripts/demo_ursim.py --log fixed_zone   # deployed practice: stutters
  python scripts/demo_ursim.py --log adaptive     # full system: keeps flowing

Pendant prerequisites (via noVNC): power on -> brake release -> load & PLAY any
program (e.g. an empty program with a Wait) -> Remote Control mode if prompted.
The replay is the IDENTICAL command path used for hardware (RTDE speed slider +
Dashboard pause/play), so a green demo here is a faithful dry-run of the cell.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.config import load_config  # noqa: E402
from hrc_safety.logging_schema import Command  # noqa: E402
from hrc_safety.robot import URRobot  # noqa: E402

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "logs")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", default="adaptive",
                    choices=["fixed_zone", "dynamic_ssm", "adaptive"],
                    help="which logged run to replay onto the robot")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="playback speed multiplier (2.0 = twice as fast)")
    ap.add_argument("--host", default=None,
                    help="robot/URSim IP (default: configs/default.yaml)")
    args = ap.parse_args()

    config = load_config()
    host = args.host or config["robot"]["host"]
    path = os.path.join(LOG_DIR, f"{args.log}.jsonl")
    if not os.path.exists(path):
        print(f"missing {path} -- run scripts/run_simulation.py first")
        return 1
    with open(path) as fh:
        records = [json.loads(line) for line in fh]
    print(f"replaying {len(records)} ticks of '{args.log}' onto {host} "
          f"(x{args.speed:g} speed) -- Ctrl-C to abort safely")

    robot = URRobot(host,
                    rtde_port=config["robot"].get("rtde_port", 30004),
                    dashboard_port=config["robot"].get("dashboard_port", 29999))

    last_key = None
    t_prev = None
    try:
        for rec in records:
            t = rec["t"]
            if t_prev is not None and t > t_prev:
                time.sleep((t - t_prev) / max(args.speed, 1e-6))
            t_prev = t
            robot.apply(Command(rec["command"]), rec["speed_fraction"])
            key = (rec.get("robot_mode"), rec["command"])
            if key != last_key:
                last_key = key
                print(f"t={t:7.2f}s  phase={rec.get('robot_mode','?'):<15}"
                      f" state={rec.get('inferred_state','?'):<11}"
                      f" -> {rec['command']:<15} speed={rec['speed_fraction']:.2f}")
    except KeyboardInterrupt:
        print("\naborted -- restoring robot to resumed / full slider")
    finally:
        # Never leave the cell paused or throttled after a demo.
        robot.apply(Command.FULL_SPEED, 1.0)
    print("replay complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
