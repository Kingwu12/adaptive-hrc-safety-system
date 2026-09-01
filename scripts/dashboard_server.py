#!/usr/bin/env python3
"""Local Xsens experiment service for the HRC Operator Motion Console.

The Xsens MVN software sends MXTP02 UDP packets to this process on port 9763.
The dashboard polls the HTTP API on port 8765. By default HTTP is localhost-only;
pass --share to allow browsers on the same trusted lab network to connect.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vg10 import VG10  # noqa: E402

from hrc_safety.analysis import fit_hmm  # noqa: E402
from hrc_safety.config import load_config  # noqa: E402
from hrc_safety.features import FeatureExtractor  # noqa: E402
from hrc_safety.lhmm.upper import STATES  # noqa: E402
from hrc_safety.mocap import (MocapBridge, NatNetV4Listener,
                              RigidBodyMonitor, load_extrinsics)  # noqa: E402
from hrc_safety.mocap.xsens_transport import PELVIS, XsensListener  # noqa: E402

ALLOWED_LABELS = {"unlabelled", "approaching", "working", "retreating", "hazard"}


def safe_id(value: object, fallback: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return clean[:48] or fallback


class DashboardState:
    def __init__(self, output_dir: Path, segment_id: int) -> None:
        self.lock = threading.RLock()
        self.output_dir = output_dir
        self.segment_id = segment_id
        self.config = load_config()
        features = self.config["features"]
        self.bridge = MocapBridge(sample_rate_hz=features["sample_rate_hz"])
        extrinsics = load_extrinsics("configs/mocap_extrinsics.yaml")
        self.optitrack_bridge = MocapBridge(
            sample_rate_hz=features["sample_rate_hz"], extrinsics=extrinsics)
        self.extractor = FeatureExtractor(
            tcp_position=self.config["scenario"]["tcp_position"],
            sample_rate_hz=features["sample_rate_hz"],
            velocity_window=features["velocity_window"],
            accel_window=features["accel_window"],
        )
        self.hmm = fit_hmm(self.config)
        self.packet_times: deque[float] = deque(maxlen=240)
        self.packets = 0
        self.last_packet_wall: float | None = None
        self.position: list[float] | None = None
        self.xsens_position: list[float] | None = None
        self.optitrack_stale = True
        self.optitrack_age_s: float | None = None
        self.feature: dict | None = None
        self.posterior: dict[str, float] = {}
        self.hmm_state: str | None = None
        self.recording = False
        self.session_id: str | None = None
        self.participant_id: str | None = None
        self.trial_id: str | None = None
        self.label = "unlabelled"
        self.recording_path: str | None = None
        self.samples_written = 0
        self.calibration_started: float | None = None
        self.file = None

    def on_sample(self, source_ts: float, position, tracked: bool, wall_time: float) -> None:
        self.bridge.on_sample(source_ts, position, tracked, wall_time)
        with self.lock:
            self.packets += 1
            self.last_packet_wall = wall_time
            self.packet_times.append(wall_time)

    def tick(self) -> None:
        now = time.monotonic()
        xsens_sample = self.bridge.tick(now)
        optitrack_sample = self.optitrack_bridge.tick(now)
        if xsens_sample is None:
            return
        # Absolute operator position comes from the tracked head rigid body in
        # robot-base coordinates. Xsens remains the articulated-motion source.
        sample = optitrack_sample
        frame = None if sample is None or sample.stale else self.extractor.push(
            sample.t, sample.position)
        posterior: dict[str, float] = {}
        state = None
        feature = None
        if frame is not None:
            feature = asdict(frame)
            beliefs = self.hmm.step(frame.as_vector())
            posterior = {name: float(beliefs[i]) for i, name in enumerate(STATES)}
            state = max(posterior, key=posterior.get)
        with self.lock:
            self.xsens_position = [float(v) for v in xsens_sample.position]
            self.position = (None if sample is None else
                             [float(v) for v in sample.position])
            self.optitrack_stale = sample is None or sample.stale
            self.optitrack_age_s = None if sample is None else sample.age_s
            self.feature = feature
            self.posterior = posterior
            self.hmm_state = state
            if self.recording and self.file is not None:
                record = {
                    "schema_version": 1,
                    "session_id": self.session_id,
                    "participant_id": self.participant_id,
                    "trial_id": self.trial_id,
                    "t": round(xsens_sample.t, 6),
                    "source_time_s": xsens_sample.motive_timestamp,
                    "position": self.position,
                    "xsens_position": self.xsens_position,
                    "stale": self.optitrack_stale,
                    "age_s": (None if self.optitrack_age_s is None else
                              round(self.optitrack_age_s, 5)),
                    "features": feature,
                    "ground_truth": self.label,
                    "hmm_state": state,
                    "hmm_posterior": posterior,
                    "model_source": "synthetic baseline",
                }
                self.file.write(json.dumps(record, separators=(",", ":")) + "\n")
                self.file.flush()
                self.samples_written += 1

    def start_session(self, participant: object, trial: object) -> dict:
        with self.lock:
            if self.recording:
                raise ValueError("A recording is already active")
            if not self.connected:
                raise ValueError("Xsens is not streaming yet")
            self.participant_id = safe_id(participant, "P00")
            self.trial_id = safe_id(trial, "T00")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.session_id = f"{self.participant_id}-{self.trial_id}-{stamp}-{uuid.uuid4().hex[:6]}"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            path = self.output_dir / f"{self.session_id}.jsonl"
            self.file = path.open("x", encoding="utf-8")
            self.recording_path = str(path.resolve())
            self.samples_written = 0
            self.label = "unlabelled"
            self.recording = True
            return {"message": f"Recording {self.session_id}", "path": self.recording_path}

    def stop_session(self) -> dict:
        with self.lock:
            if not self.recording:
                raise ValueError("No recording is active")
            self.recording = False
            if self.file is not None:
                self.file.close()
                self.file = None
            return {"message": f"Saved {self.samples_written} samples", "path": self.recording_path}

    def set_label(self, label: object) -> dict:
        value = str(label or "")
        if value not in ALLOWED_LABELS:
            raise ValueError(f"Unknown label: {value}")
        with self.lock:
            if not self.recording:
                raise ValueError("Start recording before applying labels")
            self.label = value
        return {"message": f"Ground truth: {value}"}

    def mark_calibrated(self) -> dict:
        with self.lock:
            if not self.connected:
                raise ValueError("Xsens is not streaming yet")
            self.calibration_started = time.monotonic()
        return {"message": "Calibration clock started — recalibrate before five minutes"}

    @property
    def connected(self) -> bool:
        return self.last_packet_wall is not None and time.monotonic() - self.last_packet_wall < 1.0

    def snapshot(self) -> dict:
        with self.lock:
            now = time.monotonic()
            age = None if self.last_packet_wall is None else now - self.last_packet_wall
            rate = 0.0
            recent = [t for t in self.packet_times if now - t <= 2.0]
            if len(recent) >= 2:
                rate = (len(recent) - 1) / max(recent[-1] - recent[0], 1e-6)
            calibration_elapsed = None if self.calibration_started is None else now - self.calibration_started
            return {
                "connected": self.connected,
                "packets": self.packets,
                "packet_rate_hz": round(rate, 1),
                "stale": age is None or age > 0.150,
                "age_s": None if age is None else round(age, 4),
                "position": self.position,
                "xsens_position": self.xsens_position,
                "optitrack_connected": not self.optitrack_stale,
                "optitrack_age_s": (None if self.optitrack_age_s is None else
                                    round(self.optitrack_age_s, 4)),
                "feature": self.feature,
                "posterior": self.posterior,
                "hmm_state": self.hmm_state,
                "model_source": "synthetic baseline",
                "recording": self.recording,
                "session_id": self.session_id,
                "participant_id": self.participant_id,
                "trial_id": self.trial_id,
                "label": self.label,
                "recording_path": self.recording_path,
                "samples_written": self.samples_written,
                "calibration_elapsed_s": None if calibration_elapsed is None else round(calibration_elapsed, 1),
            }


class RigControl:
    """Gripper (VG10 Modbus via robot SSH) + UR Dashboard program control."""

    def __init__(self, robot_host: str, dashboard_port: int = 29999) -> None:
        self.gripper = VG10()
        self.robot_host = robot_host
        self.dashboard_port = dashboard_port
        self.lock = threading.Lock()
        self._last_gripper: dict = {}
        self._last_gripper_t = 0.0
        self._recv = None            # RTDEReceiveInterface, opened lazily
        self._recv_error: str | None = None
        self._poses = self._load_poses()
        self.fastening_complete = threading.Event()
        self.cycle_active = False

    # ---------------------------------------------------------------- pose I/O

    def _load_poses(self) -> dict:
        """Poses freedriven and saved on the real arm 2026-08-12."""
        path = os.path.join(os.path.dirname(__file__), "..",
                            "data", "taught_poses.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"RigControl: no taught poses ({exc}); GO UP / GO DOWN "
                  f"will be unavailable.")
            return {}

    def _receiver(self):
        """Lazy RTDEReceiveInterface. Returns None if unavailable, never a
        stale pose -- a missing pose must read as missing, not as a default."""
        if self._recv is not None:
            return self._recv
        try:
            from rtde_receive import RTDEReceiveInterface
            self._recv = RTDEReceiveInterface(self.robot_host)
            self._recv_error = None
        except Exception as exc:
            self._recv = None
            self._recv_error = f"{type(exc).__name__}: {exc}"
        return self._recv

    def pose_status(self) -> dict:
        """Live TCP + joints, or an explicit reason why not."""
        recv = self._receiver()
        if recv is None:
            return {"available": False, "error": self._recv_error or "no receiver"}
        try:
            pose = recv.getActualTCPPose()
            q = recv.getActualQ()
        except Exception as exc:
            self._recv = None  # force a reconnect next poll
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        if not pose or len(pose) < 3:
            return {"available": False, "error": "empty pose"}
        return {
            "available": True,
            "tcp": [round(float(v), 4) for v in pose[:3]],
            "q": [round(float(v), 4) for v in (q or [])],
        }

    def _dash(self, *commands: str) -> list[str]:
        """Send Dashboard-server commands; return one reply line per command."""
        out: list[str] = []
        with socket.create_connection((self.robot_host, self.dashboard_port),
                                      timeout=4) as s:
            f = s.makefile("rw", newline="\n")
            f.readline()  # hello banner
            for c in commands:
                f.write(c + "\n")
                f.flush()
                out.append(f.readline().strip())
        return out

    def robot_status(self) -> dict:
        try:
            r = self._dash("robotmode", "safetystatus", "programState",
                           "get loaded program", "running")
            return {"reachable": True, "robotmode": r[0], "safety": r[1],
                    "program_state": r[2], "loaded": r[3], "running": r[4]}
        except OSError as exc:
            return {"reachable": False, "error": str(exc)}

    def robot_action(self, action: str) -> dict:
        cmds = {
            "power_on": ["power on"],
            "brake_release": ["brake release"],
            "play": ["play"],
            "pause": ["pause"],
            "stop": ["stop"],
            "unlock": ["unlock protective stop"],
        }
        if action == "run_cycle":
            return {"action": action, **self.run_cycle_only()}
        if action == "go_up":
            return {"action": action, **self.goto_pose("pose2_top")}
        if action == "go_down":
            return {"action": action, **self.goto_pose("pose1_low")}
        if action == "freedrive_on":
            return {"action": action, **self.freedrive(True)}
        if action == "freedrive_off":
            return {"action": action, **self.freedrive(False)}
        if action not in cmds:
            raise ValueError(f"Unknown robot action: {action}")
        replies = self._dash(*cmds[action])
        return {"action": action, "replies": replies}

    def gripper_action(self, action: str, channel: str, vacuum: int) -> dict:
        with self.lock:
            if action == "grip":
                out = self.gripper.grip(channel, vacuum)
            elif action == "release":
                out = self.gripper.release(channel)
            elif action == "idle":
                out = self.gripper.idle(channel)
            else:
                raise ValueError(f"Unknown gripper action: {action}")
            if out.get("stats"):
                self._last_gripper = out["stats"]
                self._last_gripper_t = time.monotonic()
            return out

    def gripper_stats(self, max_age_s: float = 2.0) -> dict:
        with self.lock:
            if time.monotonic() - self._last_gripper_t > max_age_s:
                out = self.gripper.stats()
                if out.get("stats"):
                    self._last_gripper = out["stats"]
                    self._last_gripper_t = time.monotonic()
                elif not self._last_gripper:
                    return {"error": out.get("error", "gripper unreachable")}
            return dict(self._last_gripper)

    def send_panel_cycle(self) -> dict:
        """Inject the panel-cycle task program over the primary interface.

        No .urp needed: the plain-statement script from the repo is wrapped in
        a def/end on the fly and becomes the running program. Protocol facts
        learned on the real arm 2026-08-12: the def block alone auto-starts
        (a trailing call line is a parse error), and the socket must STAY OPEN
        or the controller kills the program. First statement declares the
        VG10's payload (1.7 kg) so joint collision detection has the right
        dynamics model -- without it the shoulder trips C157A1 on the first
        acceleration. Robot must be in Remote Control.
        """
        self.close_program_socket()
        path = os.path.join(os.path.dirname(__file__), "..",
                            "sim", "ursim", "panel_cycle.script")
        with open(path, "r", encoding="utf-8") as fh:
            body = fh.read()
        prog = "def panel_cycle_t():\n"
        prog += "  set_payload(1.7, [0.0, 0.0, 0.06])\n"
        prog += "".join("  " + line + "\n" for line in body.splitlines())
        prog += "end\n"
        self._prog_sock = socket.create_connection(
            (self.robot_host, 30001), timeout=5)
        self._prog_sock.sendall(prog.encode("utf-8"))
        time.sleep(0.8)
        state = self._dash("programState", "running")
        return {"sent_bytes": len(prog), "program_state": state[0],
                "running": state[1]}

    def close_program_socket(self) -> None:
        sock = getattr(self, "_prog_sock", None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
            self._prog_sock = None

    def demo_start(self, vacuum: int) -> dict:
        """Suck the panel, then run the panel-cycle program on the arm."""
        self.fastening_complete.clear()
        self.cycle_active = True
        steps: dict = {}
        steps["grip"] = self.gripper_action("grip", "BOTH", vacuum)
        if not steps["grip"].get("ok"):
            raise ValueError("gripper grip failed: " +
                             str(steps["grip"].get("error")))
        steps["robot"] = self.send_panel_cycle()
        if "false" in steps["robot"].get("running", "").lower():
            steps["hint"] = ("Program did not start -- is the robot in "
                             "Remote Control mode and powered with brakes "
                             "released?")
        return steps

    def demo_stop(self) -> dict:
        steps: dict = {}
        self.cycle_active = False
        self.fastening_complete.clear()
        steps["robot"] = self._dash("stop")
        self.close_program_socket()
        steps["release"] = self.gripper_action("release", "BOTH", 0)
        return steps

    def cycle_event(self, action: str) -> dict:
        """Record task confirmation; never vents the gripper directly."""
        if action == "reset":
            self.fastening_complete.clear()
            return {"ok": True, "fastening_complete": False}
        if action != "fastening_complete":
            raise ValueError(f"Unknown cycle event: {action}")
        stats = self.gripper_stats(max_age_s=0.0)
        if min(stats.get("vacuum_A_permille", 0),
               stats.get("vacuum_B_permille", 0)) < 350:
            raise ValueError("fastening confirmation rejected: panel grip not verified")
        self.fastening_complete.set()
        return {"ok": True, "fastening_complete": True,
                "message": "Fastening confirmed; awaiting automated attachment checks"}

    def run_cycle_only(self) -> dict:
        """Motion check: run the panel cycle without touching the gripper."""
        return self.send_panel_cycle()

    # ------------------------------------------------------- discrete moves

    def goto_pose(self, name: str, speed: float = 0.35) -> dict:
        """Move to a taught joint pose with movej.

        movej, never movel. Learned on the real arm 2026-08-12: a linear move
        from or near full extension trips a protective stop at the singularity.
        movej goes through joint space and cannot hit that.

        Same def-only injection protocol as the panel cycle: the def block
        auto-starts, a trailing call line is a parse error, the socket must
        stay open or the controller kills the program, and set_payload must be
        the first statement or the shoulder trips C157A1 on first acceleration.
        """
        pose = self._poses.get(name)
        if not pose or "q" not in pose:
            raise ValueError(f"Unknown taught pose: {name}. "
                             f"Have: {sorted(self._poses)}")
        q = ", ".join(f"{float(v):.5f}" for v in pose["q"])
        spd = max(0.05, min(1.0, float(speed)))
        self.close_program_socket()
        prog = ("def goto_%s():\n"
                "  set_payload(1.7, [0.0, 0.0, 0.06])\n"
                "  movej([%s], a=0.8, v=%.3f)\n"
                "end\n") % (name.replace("-", "_"), q, spd)
        self._prog_sock = socket.create_connection(
            (self.robot_host, 30001), timeout=5)
        self._prog_sock.sendall(prog.encode("utf-8"))
        time.sleep(0.8)
        state = self._dash("programState", "running")
        return {"pose": name, "q": pose["q"], "speed": spd,
                "program_state": state[0], "running": state[1]}

    def freedrive(self, on: bool) -> dict:
        """Hand-guiding on or off, so poses can be re-taught without the pendant."""
        self.close_program_socket()
        if on:
            prog = ("def fd_on():\n"
                    "  set_payload(1.7, [0.0, 0.0, 0.06])\n"
                    "  freedrive_mode()\n"
                    "  while True:\n"
                    "    sync()\n"
                    "  end\n"
                    "end\n")
            self._prog_sock = socket.create_connection(
                (self.robot_host, 30001), timeout=5)
            self._prog_sock.sendall(prog.encode("utf-8"))
            time.sleep(0.5)
            return {"freedrive": True,
                    "note": "socket held open; press FREEDRIVE OFF to end"}
        replies = self._dash("stop")
        return {"freedrive": False, "replies": replies}


CONTROL_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HRC Rig Control</title><style>
body{font-family:-apple-system,sans-serif;background:#111;color:#eee;margin:0;padding:16px;max-width:520px;margin:auto}
h2{margin:14px 0 6px;font-size:15px;color:#9ad}
button{font-size:17px;padding:14px 10px;margin:4px;border:0;border-radius:10px;background:#2a2f3a;color:#eee;width:calc(50% - 12px)}
button:active{background:#3d4656}
button.big{width:calc(100% - 8px);font-weight:700}
button.go{background:#1d5c33}button.warn{background:#7a5a17}button.stop{background:#7a1d1d}
#log{font-size:12px;color:#9a9;white-space:pre-wrap;margin-top:10px}
#st{font-size:13px;line-height:1.5;background:#191d24;border-radius:10px;padding:10px;margin-top:8px}
input[type=range]{width:65%;vertical-align:middle}
.v{color:#fd9}</style></head><body>
<h2>Arm position</h2>
<div id="posebox">reading...</div>
<button class="go" onclick="post('/api/robot',{action:'go_up'})">GO UP</button>
<button class="go" onclick="post('/api/robot',{action:'go_down'})">GO DOWN</button>
<button class="warn" onclick="post('/api/robot',{action:'freedrive_on'})">Freedrive ON</button>
<button onclick="post('/api/robot',{action:'freedrive_off'})">Freedrive OFF</button>

<h2>Panel demo</h2>
<button class="big go" onclick="post('/api/demo',{action:'start',vacuum:vac()})">SUCK PANEL + RUN CYCLE</button>
<button class="big stop" onclick="post('/api/demo',{action:'stop'})">STOP CYCLE + RELEASE</button>
<button class="big warn" onclick="post('/api/cycle',{action:'fastening_complete'})">FASTENING COMPLETE</button>
<h2>Gripper &nbsp;<span class="v" id="vacv">60</span>% <input type="range" id="vac" min="10" max="80" value="60" oninput="vacv.innerText=this.value"></h2>
<button class="go" onclick="post('/api/gripper',{action:'grip',channel:'BOTH',vacuum:vac()})">Grip</button>
<button onclick="post('/api/gripper',{action:'release',channel:'BOTH'})">Release</button>
<h2>Xsens</h2>
<button class="go" onclick="post('/api/xsens/reset',{type:'grid'})">RESET (grid)</button>
<button onclick="post('/api/xsens/reset',{type:'heading'})">Heading only</button>
<button onclick="post('/api/xsens/reset',{type:'position'})">Position only</button>
<h2>Robot</h2>
<button onclick="post('/api/robot',{action:'power_on'})">Power on</button>
<button onclick="post('/api/robot',{action:'brake_release'})">Brake release</button>
<button onclick="post('/api/robot',{action:'play'})">Play</button>
<button class="warn" onclick="post('/api/robot',{action:'pause'})">Pause</button>
<button class="big stop" onclick="post('/api/robot',{action:'stop'})">STOP PROGRAM</button>
<div id="st">loading…</div><div id="log"></div>
<script>
const KEY=new URLSearchParams(location.search).get('k')||'';
function vac(){return parseInt(document.getElementById('vac').value)}
async function post(p,b){
  log('> '+p+' '+JSON.stringify(b));
  try{const r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json','X-Control-Key':KEY},body:JSON.stringify(b)});
  const j=await r.json();log(JSON.stringify(j).slice(0,220));}catch(e){log('ERR '+e)}}
function log(m){const d=document.getElementById('log');d.innerText=(m+'\\n'+d.innerText).slice(0,1500)}
async function poll(){try{
  const r=await fetch('/api/rig');const j=await r.json();
  const g=j.gripper||{},ro=j.robot||{},x=j.xsens||{},p=j.pose||{};
  const pb=document.getElementById('posebox');
  if(p.available){
    const t=p.tcp||[0,0,0];
    pb.innerHTML=`<b style="color:#6d9">TCP LIVE</b> &nbsp; x <span class=v>${t[0].toFixed(3)}</span> &nbsp; y <span class=v>${t[1].toFixed(3)}</span> &nbsp; z <span class=v>${t[2].toFixed(3)}</span> m`;
    pb.style.background='#16211a';
  }else{
    pb.innerHTML=`<b style="color:#e88">TCP NOT READABLE</b><br><span style="font-size:11px">${(p.error||'unknown')}</span><br><span style="font-size:11px;color:#e88">Live separation would be measured against a stationary phantom. Do not trust safety numbers.</span>`;
    pb.style.background='#2a1616';
  }
  document.getElementById('st').innerHTML=
   `<b>Gripper</b> vacA <span class=v>${(g.vacuum_A_permille??'?')}</span>‰ · vacB <span class=v>${(g.vacuum_B_permille??'?')}</span>‰ · pump ${(g.pump_rpm??'?')}rpm · ${(g.current_mA??'?')}mA<br>`+
   `<b>Robot</b> ${ro.robotmode??'?'} · ${ro.safety??'?'} · ${ro.program_state??'?'}<br>`+
   `<b>Xsens</b> ${x.connected?'STREAMING '+x.packet_rate_hz+'Hz':'no stream'} · pos ${x.position?x.position.map(v=>v.toFixed(2)):'—'}`;
 }catch(e){}}
setInterval(poll,1200);poll();
</script></body></html>"""


class ApiHandler(BaseHTTPRequestHandler):
    state: DashboardState
    rig: RigControl
    allow_remote_control = False
    control_key = ""

    def _headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        # X-Control-Key MUST be listed or the browser's preflight blocks every
        # rig command from the Next console (different origin to this server).
        # Symptom without it: GETs poll fine, every POST fails "Failed to fetch".
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Control-Key")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _json(self, value: dict, status: int = 200) -> None:
        self._headers(status)
        self.wfile.write(json.dumps(value).encode("utf-8"))

    def _xsens_reset(self, reset_type: str) -> dict:
        """Forward a reset to the Windows MVN laptop's keystroke listener.

        Target host:port lives in data/xsens/.mvn_remote (editable without
        restart). Default is the Windows mobile-hotspot host address.
        """
        import urllib.request
        remote_file = Path("data/xsens/.mvn_remote")
        target = "192.168.137.1:9764"
        if remote_file.exists():
            target = remote_file.read_text().strip() or target
        url = f"http://{target}/reset?type={reset_type}"
        try:
            with urllib.request.urlopen(url, timeout=4) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"MVN listener unreachable at {target}: {exc}"}

    def do_OPTIONS(self) -> None:
        self._headers(204)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/api/status":
            self._json(self.state.snapshot())
        elif path == "/api/rig":
            self._json({
                "gripper": self.rig.gripper_stats(),
                "robot": self.rig.robot_status(),
                "pose": self.rig.pose_status(),
                "xsens": self.state.snapshot(),
                "cycle": {"active": self.rig.cycle_active,
                          "fastening_complete": self.rig.fastening_complete.is_set()},
            })
        elif path in ("/control", "/control/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(CONTROL_PAGE.encode("utf-8"))
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        try:
            remote = self.client_address[0] not in {"127.0.0.1", "::1"}
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            rig_paths = {"/api/gripper", "/api/robot", "/api/demo", "/api/cycle", "/api/xsens/reset"}
            if self.path in rig_paths:
                # rig control needs the key from any remote browser
                if remote and self.headers.get("X-Control-Key", "") != self.control_key:
                    return self._json({"error": "Bad or missing control key"}, 403)
                if self.path == "/api/gripper":
                    result = self.rig.gripper_action(
                        str(body.get("action")), str(body.get("channel", "BOTH")),
                        int(body.get("vacuum", 60)))
                elif self.path == "/api/robot":
                    result = self.rig.robot_action(str(body.get("action")))
                elif self.path == "/api/xsens/reset":
                    result = self._xsens_reset(str(body.get("type", "grid")))
                elif self.path == "/api/cycle":
                    result = self.rig.cycle_event(str(body.get("action")))
                else:
                    if body.get("action") == "start":
                        result = self.rig.demo_start(int(body.get("vacuum", 60)))
                    else:
                        result = self.rig.demo_stop()
                return self._json(result)
            if remote and not self.allow_remote_control:
                return self._json({"error": "Remote browsers are view-only"}, 403)
            if self.path == "/api/session/start":
                result = self.state.start_session(body.get("participant_id"), body.get("trial_id"))
            elif self.path == "/api/session/stop":
                result = self.state.stop_session()
            elif self.path == "/api/label":
                result = self.state.set_label(body.get("label"))
            elif self.path == "/api/calibration/mark":
                result = self.state.mark_calibrated()
            else:
                return self._json({"error": "Not found"}, 404)
            self._json(result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": f"Internal error: {exc}"}, 500)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--share", action="store_true", help="allow access from the trusted local network")
    parser.add_argument("--allow-remote-control", action="store_true", help="let shared-network browsers record and label")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--udp-port", type=int, default=9763)
    parser.add_argument("--segment", type=int, default=PELVIS)
    parser.add_argument("--out", default="data/xsens")
    args = parser.parse_args()

    state = DashboardState(Path(args.out), args.segment)
    listener = XsensListener(state, port=args.udp_port, segment_id=args.segment)
    listener.start()
    optitrack_monitor = RigidBodyMonitor()
    optitrack_listener = NatNetV4Listener(
        state.optitrack_bridge,
        head_rigid_body_id=1,
        local_address="127.0.0.1",
        monitor=optitrack_monitor,
        nominal_rate_hz=120.0,
    )
    optitrack_listener.start()
    stop = threading.Event()
    rig = RigControl(state.config["robot"]["host"],
                     state.config["robot"].get("dashboard_port", 29999))
    key_file = Path(args.out) / ".control_key"
    if key_file.exists():
        control_key = key_file.read_text().strip()
    else:
        control_key = uuid.uuid4().hex[:8]
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(control_key)

    def ticker() -> None:
        dt = 1.0 / state.config["features"]["sample_rate_hz"]
        while not stop.is_set():
            state.tick()
            time.sleep(dt)

    tick_thread = threading.Thread(target=ticker, daemon=True)
    tick_thread.start()
    ApiHandler.state = state
    ApiHandler.rig = rig
    ApiHandler.control_key = control_key
    ApiHandler.allow_remote_control = args.allow_remote_control
    host = "0.0.0.0" if args.share else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.http_port), ApiHandler)
    print(f"Dashboard sensor service: http://{host}:{args.http_port}")
    print(f"RIG CONTROL PAGE: http://<this-mac-ip>:{args.http_port}/control?k={control_key}")
    print(f"Xsens MVN target: UDP {args.udp_port} · Position + Quaternion · segment {args.segment}")
    print(f"Recordings: {Path(args.out).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        listener.stop()
        optitrack_listener.stop()
        server.server_close()
        if state.file is not None:
            state.file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
