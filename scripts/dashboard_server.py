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
from hrc_safety.mocap import MocapBridge  # noqa: E402
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
        sample = self.bridge.tick(now)
        if sample is None:
            return
        frame = self.extractor.push(sample.t, sample.position)
        posterior: dict[str, float] = {}
        state = None
        feature = None
        if frame is not None:
            feature = asdict(frame)
            beliefs = self.hmm.step(frame.as_vector())
            posterior = {name: float(beliefs[i]) for i, name in enumerate(STATES)}
            state = max(posterior, key=posterior.get)
        with self.lock:
            self.position = [float(v) for v in sample.position]
            self.feature = feature
            self.posterior = posterior
            self.hmm_state = state
            if self.recording and self.file is not None:
                record = {
                    "schema_version": 1,
                    "session_id": self.session_id,
                    "participant_id": self.participant_id,
                    "trial_id": self.trial_id,
                    "t": round(sample.t, 6),
                    "source_time_s": sample.motive_timestamp,
                    "position": self.position,
                    "stale": sample.stale,
                    "age_s": round(sample.age_s, 5),
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
            "load_panel_cycle": ["load panel_cycle.urp"],
            "play": ["play"],
            "pause": ["pause"],
            "stop": ["stop"],
            "unlock": ["unlock protective stop"],
        }
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
        a def/end on the fly and becomes the running program (the same ritual
        verified on URSim and the real arm). Robot must be in Remote Control.
        """
        path = os.path.join(os.path.dirname(__file__), "..",
                            "sim", "ursim", "panel_cycle.script")
        with open(path, "r", encoding="utf-8") as fh:
            body = fh.read()
        prog = "def panel_cycle_t():\n"
        prog += "".join("  " + line + "\n" for line in body.splitlines())
        prog += "end\npanel_cycle_t()\n"
        with socket.create_connection((self.robot_host, 30001), timeout=4) as s:
            s.sendall(prog.encode("utf-8"))
            time.sleep(0.8)
        state = self._dash("programState", "running")
        return {"sent_bytes": len(prog), "program_state": state[0],
                "running": state[1]}

    def demo_start(self, vacuum: int) -> dict:
        """Suck the panel, then run the panel-cycle program on the arm."""
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
        steps["robot"] = self._dash("stop")
        steps["release"] = self.gripper_action("release", "BOTH", 0)
        return steps


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
<h2>Panel demo</h2>
<button class="big go" onclick="post('/api/demo',{action:'start',vacuum:vac()})">SUCK PANEL + RUN CYCLE</button>
<button class="big stop" onclick="post('/api/demo',{action:'stop'})">STOP CYCLE + RELEASE</button>
<h2>Gripper &nbsp;<span class="v" id="vacv">60</span>% <input type="range" id="vac" min="10" max="80" value="60" oninput="vacv.innerText=this.value"></h2>
<button class="go" onclick="post('/api/gripper',{action:'grip',channel:'BOTH',vacuum:vac()})">Grip</button>
<button onclick="post('/api/gripper',{action:'release',channel:'BOTH'})">Release</button>
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
  const g=j.gripper||{},ro=j.robot||{},x=j.xsens||{};
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _json(self, value: dict, status: int = 200) -> None:
        self._headers(status)
        self.wfile.write(json.dumps(value).encode("utf-8"))

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
                "xsens": self.state.snapshot(),
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
            rig_paths = {"/api/gripper", "/api/robot", "/api/demo"}
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
    stop = threading.Event()
    rig = RigControl(state.config["robot"]["host"],
                     state.config["robot"].get("dashboard_port", 29999))
    control_key = uuid.uuid4().hex[:8]

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
        server.server_close()
        if state.file is not None:
            state.file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
