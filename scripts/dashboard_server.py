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


class ApiHandler(BaseHTTPRequestHandler):
    state: DashboardState
    allow_remote_control = False

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
        if self.path == "/api/status":
            self._json(self.state.snapshot())
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        try:
            if self.client_address[0] not in {"127.0.0.1", "::1"} and not self.allow_remote_control:
                return self._json({"error": "Remote browsers are view-only"}, 403)
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
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

    def ticker() -> None:
        dt = 1.0 / state.config["features"]["sample_rate_hz"]
        while not stop.is_set():
            state.tick()
            time.sleep(dt)

    tick_thread = threading.Thread(target=ticker, daemon=True)
    tick_thread.start()
    ApiHandler.state = state
    ApiHandler.allow_remote_control = args.allow_remote_control
    host = "0.0.0.0" if args.share else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.http_port), ApiHandler)
    print(f"Dashboard sensor service: http://{host}:{args.http_port}")
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
