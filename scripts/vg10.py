#!/usr/bin/env python3
"""VG10 G1 vacuum gripper control -- direct Modbus RTU, no URCap needed.

The lab's OnRobot VG10 is a first-generation (G1, 2018) unit. The unified
OnRobot URCap 6.x installed on the UR10 speaks a newer protocol and can NEVER
detect it. The G1 instead exposes documented Modbus RTU on the tool RS485
(115200 8E1, slave 0x41), which this script drives through the robot
controller's /dev/ttyTool via SSH (key auth installed on the robot).

Robot prerequisites (pendant, Installation > General > Tool I/O -- saved in
the installation, one-time):
  Controlled by: User; Communication Interface enabled, 115200 / Even / One;
  Tool Output Voltage: 24V.

Usage (from the Mac on the robot link):
  python scripts/vg10.py stats
  python scripts/vg10.py grip --channel A --vacuum 40
  python scripts/vg10.py release
  python scripts/vg10.py idle

Also importable: from vg10 import VG10; VG10().grip("A", 40)
Verified live on the real arm 2026-08-12: grip spun the pump to 18750 rpm,
release returned it to idle.
"""
from __future__ import annotations

import argparse
import json
import subprocess

ROBOT = "root@192.168.2.101"
CHANNELS = {"A": [0], "B": [1], "BOTH": [0, 1]}

# python2 agent executed on the robot controller; one JSON line out.
_AGENT = r'''
import os, time, struct, json, sys

def crc16(d):
    crc = 0xFFFF
    for b in d:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)

def frame(*payload):
    b = bytearray(payload); b += crc16(b); return bytes(b)

def xact(fd, req, wait=0.35, retries=3):
    for _ in range(retries):
        os.write(fd, req); time.sleep(wait)
        try:
            r = os.read(fd, 64)
            if r: return r
        except OSError:
            pass
    return ""

def stats(fd):
    r = xact(fd, frame(0x41, 0x03, 0x00, 0x12, 0x00, 0x07))
    if not (r and len(r) >= 17 and ord(r[0]) == 0x41):
        return None
    v = struct.unpack(">7H", r[3:17])
    return {"vacuum_A_permille": v[0], "vacuum_B_permille": v[1],
            "current_mA": v[2], "supply_mV": v[3], "int5V_mV": v[4],
            "temp_c": v[5] / 100.0, "pump_rpm": v[6]}

import base64
cmd = json.loads(base64.b64decode(sys.argv[1]))
fd = os.open("/dev/ttyTool", os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
out = {"ok": True, "cmd": cmd["op"]}
try:
    for reg in cmd.get("regs", []):
        # write single register: fc 0x06, reg addr, value
        r = xact(fd, frame(0x41, 0x06, 0x00, reg[0],
                           (reg[1] >> 8) & 0xFF, reg[1] & 0xFF))
        if not r:
            out["ok"] = False; out["error"] = "no reply on write reg %d" % reg[0]
    if cmd.get("settle"):
        time.sleep(cmd["settle"])
    s = stats(fd)
    if s is None:
        out["ok"] = False; out["error"] = out.get("error", "no reply on stats read")
    else:
        out["stats"] = s
finally:
    os.close(fd)
print(json.dumps(out))
'''


class VG10:
    """Grip/release/idle + telemetry for the G1 over the robot's tool RS485."""

    def __init__(self, robot: str = ROBOT) -> None:
        self.robot = robot

    def _run(self, op: str, regs: list, settle: float = 0.0) -> dict:
        import base64
        cmd = json.dumps({"op": op, "regs": regs, "settle": settle})
        b64 = base64.b64encode(cmd.encode()).decode()
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
             self.robot, "python2 - " + b64],
            input=_AGENT, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            return {"ok": False, "error": detail or f"ssh exited {proc.returncode}"}
        lines = proc.stdout.strip().splitlines()
        if not lines:
            return {"ok": False, "error": "robot SSH agent returned no output"}
        line = lines[-1]
        try:
            return json.loads(line)
        except ValueError:
            return {"ok": False, "error": proc.stderr.strip() or line}

    def grip(self, channel: str = "BOTH", vacuum_pct: int = 60,
             settle: float = 1.0) -> dict:
        vacuum_pct = max(0, min(80, int(vacuum_pct)))
        regs = [[r, (1 << 8) | vacuum_pct] for r in CHANNELS[channel.upper()]]
        return self._run("grip", regs, settle)

    def release(self, channel: str = "BOTH", settle: float = 0.8) -> dict:
        regs = [[r, 0x0000] for r in CHANNELS[channel.upper()]]
        return self._run("release", regs, settle)

    def idle(self, channel: str = "BOTH") -> dict:
        regs = [[r, 0x0200] for r in CHANNELS[channel.upper()]]
        return self._run("idle", regs, 0.3)

    def stats(self) -> dict:
        return self._run("stats", [], 0.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("op", choices=["grip", "release", "idle", "stats"])
    ap.add_argument("--channel", default="BOTH", choices=["A", "B", "BOTH"])
    ap.add_argument("--vacuum", type=int, default=60,
                    help="target vacuum %% for grip (0-80, default 60)")
    args = ap.parse_args()
    g = VG10()
    if args.op == "grip":
        out = g.grip(args.channel, args.vacuum)
    elif args.op == "release":
        out = g.release(args.channel)
    elif args.op == "idle":
        out = g.idle(args.channel)
    else:
        out = g.stats()
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
