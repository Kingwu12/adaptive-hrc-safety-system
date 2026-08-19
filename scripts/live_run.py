#!/usr/bin/env python3
"""LIVE supervision loop: Xsens stream -> controller -> robot, in real time.

The wire between the existing pieces: XsensListener (UDP :9763 from the MVN
Windows machine) -> MocapBridge -> FeatureExtractor -> ONE controller rung ->
robot.apply().  MockRobot by default; --robot ur drives the real UR10.

Safety posture:
  - robot held at PROTECTIVE_STOP until the first tracked mocap sample AND the
    feature extractor have both warmed up (never move blind)
  - tracking staleness (> bridge window) -> PROTECTIVE_STOP (never optimistic)
  - Ctrl-C restores full speed unless --exit-stop (repo convention: never
    leave the cell silently paused; the pendant is the recovery surface)

--record writes the SAME raw JSONL schema as record_mocap.py, so every live
run is also a trace that replays offline through ALL rungs (scripts/replay.py
is the scoring path; one live trial, three scored controllers).

--selftest runs the whole chain on a scripted fake stream (approach -> dwell
-> dropout) with MockRobot and a simulated clock -- bench-tests the wiring
with zero hardware attached.

  python scripts/live_run.py --selftest
  python scripts/live_run.py --controller fixed_zone            # mock robot
  python scripts/live_run.py --controller adaptive --robot ur \
      --extrinsics configs/mocap_extrinsics.yaml --record data/mocap/t01.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.analysis import build_controller, fit_hmm  # noqa: E402
from hrc_safety.config import load_config  # noqa: E402
from hrc_safety.features import FeatureExtractor  # noqa: E402
from hrc_safety.logging_schema import Command  # noqa: E402
from hrc_safety.mocap import MocapBridge, load_extrinsics  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")
NEEDS_HMM = ("adaptive", "adaptive_no_pred", "adaptive_no_state")


def _make_robot(kind: str, config: dict, host: str | None):
    if kind == "mock":
        from hrc_safety.robot import MockRobot
        return MockRobot()
    from hrc_safety.robot import URRobot
    r = config["robot"]
    return URRobot(host or r["host"], rtde_port=r.get("rtde_port", 30004),
                   dashboard_port=r.get("dashboard_port", 29999))


def _make_features(config: dict) -> FeatureExtractor:
    f = config["features"]
    return FeatureExtractor(
        config["scenario"]["tcp_position"],
        sample_rate_hz=f["sample_rate_hz"],
        velocity_window=f["velocity_window"],
        accel_window=f["accel_window"],
    )


def _make_controller(name: str, config: dict):
    fitted = fit_hmm(config) if name in NEEDS_HMM else None
    return build_controller(name, config, fitted)


def _make_listener(args, bridge):
    """Pick the sensing transport. Both end at MocapBridge.on_sample, so
    nothing below this line changes when the tracker changes."""
    if args.tracker == "natnet":
        from hrc_safety.mocap.natnet_transport import NatNetListener
        if not args.motive_host:
            raise SystemExit("--tracker natnet requires --motive-host (the "
                             "machine running Motive)")
        listener = NatNetListener(bridge, server_ip=args.motive_host,
                                  rigid_body_id=args.rigid_body,
                                  data_port=args.port if args.port != 9763
                                  else 1511)
        if not listener.connect():
            raise SystemExit(f"Motive at {args.motive_host} did not answer "
                             "NAT_CONNECT. Refusing to start a run blind.")
        print(f"natnet: connected to {listener.server_info[0]} "
              f"(NatNet {listener.server_info[2]}), rigid body "
              f"{args.rigid_body}")
        return listener
    from hrc_safety.mocap.xsens_transport import PELVIS, XsensListener
    return XsensListener(bridge, port=args.port,
                         segment_id=args.segment or PELVIS)


def _raw_line(s) -> str:
    """Identical schema to record_mocap.py so live runs double as traces."""
    return json.dumps({
        "t": round(s.t, 6), "pos": list(map(float, s.position)),
        "stale": s.stale, "age_s": round(s.age_s, 4),
        "motive_timestamp": s.motive_timestamp})


def run_live(args) -> int:
    config = load_config()
    ext = load_extrinsics(args.extrinsics) if args.extrinsics else None
    if ext is None and args.robot == "ur":
        print("WARNING: no --extrinsics; distances are in the MOCAP frame, "
              "not the robot frame. Calibrate first (calibrate_mocap.py) "
              "before trusting any live decision on the real arm.")

    bridge = MocapBridge(sample_rate_hz=config["features"]["sample_rate_hz"],
                         extrinsics=ext)
    listener = _make_listener(args, bridge)
    listener.start()

    fx = _make_features(config)
    controller = _make_controller(args.controller, config)
    robot = _make_robot(args.robot, config, args.host)

    rec_fh = None
    if args.record:
        os.makedirs(os.path.dirname(args.record) or ".", exist_ok=True)
        rec_fh = open(args.record, "a")

    dt = 1.0 / config["features"]["sample_rate_hz"]
    robot.apply(Command.PROTECTIVE_STOP, 0.0)  # held until tracking is live
    print(f"live_run: {args.controller} -> {args.robot} robot; "
          f"listening udp:{args.port}; robot HELD STOPPED until tracking "
          f"warms up. Ctrl-C to end.")

    last_print = None
    tcp_misses = 0
    # ~0.25 s of missing pose at the configured rate before we stop the cell.
    tcp_miss_limit = max(1, int(0.25 * config["features"]["sample_rate_hz"]))
    if args.robot == "ur" and robot.actual_tcp() is None:
        print("WARNING: robot pose is NOT readable. Live separation would be "
              "measured against a stationary phantom. The cell will be held "
              "stopped until the pose becomes available.")
    t_end = time.monotonic() + args.duration if args.duration else None
    try:
        while t_end is None or time.monotonic() < t_end:
            now = time.monotonic()
            s = bridge.tick(now)
            if s is None:            # no tracked sample yet: stay stopped
                time.sleep(dt)
                continue
            if rec_fh:
                rec_fh.write(_raw_line(s) + "\n")
            if s.stale:
                robot.apply(Command.PROTECTIVE_STOP, 0.0)
                key = ("STALE", "protective_stop")
                if key != last_print:
                    last_print = key
                    print(f"t={s.t:7.2f}s  TRACKING LOST (age {s.age_s:.2f}s)"
                          f" -> protective_stop")
                time.sleep(dt)
                continue
            # CORRECTNESS: separation must be measured to where the arm ACTUALLY
            # is, not to the static config TCP. A stale or missing pose is a
            # stop condition, never a reason to fall back to the config value.
            tcp_now = robot.actual_tcp()
            if tcp_now is not None:
                fx.set_tcp(tcp_now)
                tcp_misses = 0
            elif args.robot == "ur":
                tcp_misses += 1
                if tcp_misses >= tcp_miss_limit:
                    robot.apply(Command.PROTECTIVE_STOP, 0.0)
                    if last_print != ("NO_TCP", "protective_stop"):
                        last_print = ("NO_TCP", "protective_stop")
                        print(f"t={s.t:7.2f}s  ROBOT POSE UNAVAILABLE "
                              f"({tcp_misses} ticks) -> protective_stop")
                    time.sleep(dt)
                    continue

            frame = fx.push(s.t, s.position)
            if frame is None:        # feature warm-up: stay stopped
                time.sleep(dt)
                continue
            rec = controller.decide(frame)
            robot.apply(Command(rec.command), rec.speed_fraction)
            key = (rec.inferred_state, rec.command)
            if key != last_print:
                last_print = key
                print(f"t={s.t:7.2f}s  d={frame.d:5.2f}m "
                      f"state={rec.inferred_state:<11} zone={rec.zone:<7}"
                      f" -> {rec.command:<15} speed={rec.speed_fraction:.2f}")
            time.sleep(dt)
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        listener.stop()
        if rec_fh:
            rec_fh.close()
        if args.exit_stop:
            robot.apply(Command.PROTECTIVE_STOP, 0.0)
            print("exit: robot left STOPPED (--exit-stop).")
        else:
            robot.apply(Command.FULL_SPEED, 1.0)
            print("exit: robot restored to full speed.")
    return 0


def selftest() -> int:
    """Whole chain on a simulated clock + scripted stream. No hardware."""
    config = load_config()
    from hrc_safety.robot import MockRobot

    bridge = MocapBridge(sample_rate_hz=config["features"]["sample_rate_hz"])
    fx = _make_features(config)
    controller = _make_controller("fixed_zone", config)
    robot = MockRobot()
    dt = 1.0 / config["features"]["sample_rate_hz"]

    tcp = config["scenario"]["tcp_position"]
    commands: list[str] = []

    def step(k: int, pos=None) -> None:
        now = k * dt
        if pos is not None:
            bridge.on_sample(motive_ts=now, pos_xyz=pos, tracked=True,
                             wall_time=now)
        s = bridge.tick(now)
        if s is None:
            return
        if s.stale:
            robot.apply(Command.PROTECTIVE_STOP, 0.0)
            commands.append("stale_stop")
            return
        frame = fx.push(s.t, s.position)
        if frame is None:
            return
        rec = controller.decide(frame)
        robot.apply(Command(rec.command), rec.speed_fraction)
        commands.append(rec.command)

    # Phase 1: walk in from 4.0 m to 0.3 m of the column over 4 s.
    n1 = int(4.0 / dt)
    for k in range(n1):
        x = 4.0 - (4.0 - 0.3) * (k / max(n1 - 1, 1))
        step(k, [tcp[0] + x, tcp[1], 0.0])
    # Phase 2: dwell close for 0.5 s.
    n2 = int(0.5 / dt)
    for k in range(n1, n1 + n2):
        step(k, [tcp[0] + 0.3, tcp[1], 0.0])
    # Phase 3: stream dropout for 0.5 s (ticks, no samples).
    n3 = int(0.5 / dt)
    for k in range(n1 + n2, n1 + n2 + n3):
        step(k, None)

    ok = True
    if "full_speed" not in commands:
        ok = False
        print("FAIL: never reached full_speed while far away")
    if commands and not any(c == "protective_stop"
                            for c in commands[:n1 + n2]):
        ok = False
        print("FAIL: never protective_stopped during close approach")
    if "stale_stop" not in commands:
        ok = False
        print("FAIL: dropout did not trigger the staleness stop")
    if not robot.stopped:
        ok = False
        print("FAIL: robot not left stopped after dropout")
    uniq = []
    for c in commands:
        if not uniq or uniq[-1] != c:
            uniq.append(c)
    print(f"selftest command sequence: {' -> '.join(uniq)}")
    print(f"selftest ticks={len(commands)} stops={robot.stop_count}")
    print("SELFTEST PASS" if ok else "SELFTEST FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--controller", default="adaptive",
                    choices=["fixed_zone", "dynamic_ssm", "adaptive"])
    ap.add_argument("--robot", default="mock", choices=["mock", "ur"],
                    help="mock = console only (default); ur = real arm/URSim")
    ap.add_argument("--host", default=None, help="robot IP (default: config)")
    ap.add_argument("--tracker", default="xsens", choices=["xsens", "natnet"],
                    help="sensing transport (default: xsens)")
    ap.add_argument("--motive-host", default=None,
                    help="IP of the machine running Motive (--tracker natnet)")
    ap.add_argument("--rigid-body", type=int, default=1,
                    help="Motive rigid body ID to track (--tracker natnet)")
    ap.add_argument("--port", type=int, default=9763, help="Xsens UDP port")
    ap.add_argument("--segment", type=int, default=None,
                    help="MVN segment ID (default: pelvis)")
    ap.add_argument("--extrinsics", default=None,
                    help="configs/mocap_extrinsics.yaml from calibrate_mocap")
    ap.add_argument("--record", default=None,
                    help="also record the raw stream (record_mocap schema)")
    ap.add_argument("--duration", type=float, default=None,
                    help="stop after N seconds (default: run until Ctrl-C)")
    ap.add_argument("--exit-stop", action="store_true",
                    help="leave the robot STOPPED on exit instead of full")
    ap.add_argument("--selftest", action="store_true",
                    help="scripted fake stream + MockRobot; no hardware")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return run_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
