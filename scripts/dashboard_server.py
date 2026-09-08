#!/usr/bin/env python3
"""Local Xsens experiment service for the HRC Operator Motion Console.

The Xsens MVN software sends MXTP02 UDP packets to this process on port 9763.
The dashboard polls the HTTP API on port 8765. By default HTTP is localhost-only;
pass --share to allow browsers on the same trusted lab network to connect.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vg10 import VG10  # noqa: E402

from hrc_safety.analysis import build_controller, fit_hmm  # noqa: E402
from hrc_safety.config import load_config  # noqa: E402
from hrc_safety.features import FeatureExtractor  # noqa: E402
from hrc_safety.lhmm.upper import (STATES, GaussianMixtureEmissions)  # noqa: E402
from hrc_safety.pilot_model import load_upper_hmm  # noqa: E402
from hrc_safety.mocap import (MocapBridge, NatNetV4Listener,
                              RigidBodyMonitor, load_extrinsics)  # noqa: E402
from hrc_safety.mocap.xsens_transport import (  # noqa: E402
    MVN_FULL_BODY_SEGMENTS, PELVIS, XsensListener)

ALLOWED_PHASE_LABELS = {"unlabelled", "approaching", "working", "retreating"}
ALLOWED_EVENT_LABELS = {"none", "hazard", "distractor"}
ALLOWED_BLOCK_LABELS = {"A", "B", "C"}
ALLOWED_CONTROLLER_CONDITIONS = {"fixed zone", "reactive SSM", "predictive SSM"}
ALLOWED_PLANNED_EVENTS = {"clean", "distractor", "rapid intrusion"}
ALLOWED_COLLECTION_MODES = {
    "participant_study", "qualification", "model_development",
}
CONTROLLER_IMPLEMENTATIONS = {
    "fixed zone": "fixed_zone",
    "reactive SSM": "dynamic_ssm",
    "predictive SSM": "adaptive",
}
CONTROLLER_ORDERS = (
    ("fixed zone", "reactive SSM", "predictive SSM"),
    ("fixed zone", "predictive SSM", "reactive SSM"),
    ("reactive SSM", "fixed zone", "predictive SSM"),
    ("reactive SSM", "predictive SSM", "fixed zone"),
    ("predictive SSM", "fixed zone", "reactive SSM"),
    ("predictive SSM", "reactive SSM", "fixed zone"),
)
EVENT_ORDERS = (
    ("clean", "distractor", "rapid intrusion"),
    ("clean", "rapid intrusion", "distractor"),
    ("distractor", "clean", "rapid intrusion"),
    ("distractor", "rapid intrusion", "clean"),
    ("rapid intrusion", "clean", "distractor"),
    ("rapid intrusion", "distractor", "clean"),
)
GUIDED_PROTOCOL_LABELS = (
    ("unlabelled", "none"),  # collect panel and move to the marked start position
    ("approaching", "none"), # normal approach with the panel
    ("working", "none"),     # place, align, and fasten at the work position
    ("retreating", "none"),  # return to the start position
    ("unlabelled", "none"),  # reset before the cued-hazard sequence
    ("approaching", "none"), # second approach
    ("working", "none"),     # resume the panel task
    ("working", "none"),     # second task interval; event occurs during lift
    ("retreating", "none"),  # controlled recovery and retreat
    ("unlabelled", "none"),  # sequence complete
)

PHYSICAL_STEP_WARNINGS = {
    2: "Panel aligned. Suction will turn on and both cups will be verified.",
    3: "Cell clear. The robot lift and assigned event window will start together.",
    8: "Cell clear. The robot will lower the panel to the taught loading pose.",
    9: "Panel supported at the verified low pose. Suction will release and the run will save.",
}

PARTICIPANT_FORM_URLS = {
    "intake": "https://docs.google.com/forms/d/e/1FAIpQLSce3ywyZ9OFginm-8-Kk2GqH5rSl4UxfDqiieAg5iomivF3xA/viewform",
    "block": "https://docs.google.com/forms/d/e/1FAIpQLSeKgkIe5wdqEuFGnOuGxPpqD8ssQdSAR09oxrnwEQyzCPJviA/viewform",
    "end": "https://docs.google.com/forms/d/e/1FAIpQLSd4gfX2ljOfRFxyeYq2B-haGNhENzA6dCjnmhYTIXGpVxc87g/viewform",
}


def safe_id(value: object, fallback: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return clean[:48] or fallback


def assigned_study_slot(participant_id: object, block: str, within: int) -> tuple[str, str]:
    """Return the counterbalanced controller and event fixed for one study slot."""
    match = re.search(r"(\d+)", safe_id(participant_id, "P01"))
    participant_number = max(1, int(match.group(1)) if match else 1)
    seed = participant_number - 1
    block_index = ("A", "B", "C").index(block)
    controller = CONTROLLER_ORDERS[seed % len(CONTROLLER_ORDERS)][block_index]
    events = EVENT_ORDERS[(seed + block_index) % len(EVENT_ORDERS)]
    return controller, events[within - 1]


class RunCatalog:
    """Index saved recordings and keep the local participant-name registry."""

    REQUIRED_LABELS = ("approaching", "working", "retreating")
    EXPECTED_SEQUENCE = (
        "approaching", "working", "retreating",
        "approaching", "working", "retreating",
    )

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.registry_path = output_dir / "participants.json"
        self.lock = threading.RLock()
        self._cache: dict[str, tuple[int, int, dict]] = {}

    @staticmethod
    def _clean_name(value: object, collection_mode: str) -> str:
        name = re.sub(r"[\x00-\x1f]+", " ", str(value or "")).strip()
        if not name and collection_mode == "model_development":
            raise ValueError("Enter a participant name")
        return name[:80]

    def _load_registry(self) -> dict[str, dict]:
        if not self.registry_path.exists():
            return {}
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            rows = payload.get("participants", [])
            return {
                safe_id(row.get("id"), ""): {
                    "id": safe_id(row.get("id"), ""),
                    "name": str(row.get("name", "")).strip()[:80],
                    "created_at": row.get("created_at"),
                    "collection_mode": (
                        row.get("collection_mode")
                        if row.get("collection_mode") in ALLOWED_COLLECTION_MODES
                        else "model_development"
                    ),
                }
                for row in rows if safe_id(row.get("id"), "")
            }
        except (OSError, ValueError, TypeError):
            return {}

    def _save_registry(self, participants: dict[str, dict]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = {"participants": sorted(participants.values(), key=lambda row: row["id"])}
        temporary = self.registry_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.registry_path)

    @staticmethod
    def _started_at(session_id: str, fallback_timestamp: float) -> str:
        match = re.search(r"-(\d{8}-\d{6})-[0-9a-fA-F]+$", session_id)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").isoformat()
            except ValueError:
                pass
        return datetime.fromtimestamp(fallback_timestamp).isoformat(timespec="seconds")

    @classmethod
    def _quality(cls, samples: int, duration_s: float, rate_hz: float,
                 stale_ratio: float, label_counts: dict[str, int],
                 sequence: list[str], invalid_rows: int,
                 event_counts: dict[str, int] | None = None,
                 planned_event: str | None = None) -> dict:
        score = 100
        issues: list[str] = []
        missing = [label for label in cls.REQUIRED_LABELS
                   if label_counts.get(label, 0) == 0]
        if missing:
            score -= 15 * len(missing)
            issues.append("missing " + ", ".join(missing))
        event_counts = event_counts or {}
        if planned_event == "rapid intrusion" and event_counts.get("hazard", 0) == 0:
            score -= 15
            issues.append("missing planned rapid-intrusion event")
        elif planned_event == "distractor" and event_counts.get("distractor", 0) == 0:
            score -= 15
            issues.append("missing planned distractor event")
        elif planned_event == "clean" and (
            event_counts.get("hazard", 0) or event_counts.get("distractor", 0)
        ):
            score -= 15
            issues.append("unexpected event label in clean trial")
        elif planned_event is None and event_counts.get("hazard", 0) == 0:
            # Preserve the legacy quality rule for older guided-run files.
            score -= 15
            issues.append("missing cued hazard event")
        if tuple(sequence) != cls.EXPECTED_SEQUENCE:
            score -= 15
            issues.append("phase order or completion differs from the guided run")
        if duration_s < 30:
            score -= 20
            issues.append("run is under 30 seconds")
        if rate_hz < 40 or rate_hz > 80:
            score -= 15
            issues.append(f"capture rate is {rate_hz:.1f} Hz")
        if stale_ratio > 0.05:
            score -= 30
            issues.append(f"{stale_ratio * 100:.1f}% stale tracking")
        elif stale_ratio > 0.01:
            score -= 15
            issues.append(f"{stale_ratio * 100:.1f}% stale tracking")
        if rate_hz > 0:
            short = [label for label in cls.REQUIRED_LABELS
                     if 0 < label_counts.get(label, 0) / rate_hz < 2.0]
            if short:
                score -= 10
                issues.append("too little " + ", ".join(short) + " data")
        if invalid_rows:
            score -= 10
            issues.append(f"{invalid_rows} unreadable samples")
        score = max(0, score)
        if score >= 85 and not missing:
            grade, label = "good", "GOOD"
        elif score >= 60:
            grade, label = "review", "REVIEW"
        else:
            grade, label = "repeat", "REPEAT"
        if not issues:
            issues.append("all phases captured in order with stable tracking")
        return {"grade": grade, "label": label, "score": score, "reasons": issues}

    def _summarize(self, path: Path, stat) -> dict:
        samples = stale = invalid = 0
        first_t = last_t = None
        session_id = path.stem
        participant_id = "P00"
        trial_id = "T00"
        block_label = controller_condition = planned_event = None
        collection_mode = "model_development"
        label_counts: dict[str, int] = {}
        event_counts: dict[str, int] = {}
        sequence: list[str] = []
        previous_label = None
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    invalid += 1
                    continue
                samples += 1
                if samples == 1:
                    session_id = str(row.get("session_id") or path.stem)
                    participant_id = safe_id(row.get("participant_id"), "P00")
                    trial_id = safe_id(row.get("trial_id"), "T00")
                    block_label = row.get("block_label")
                    controller_condition = row.get("controller_condition")
                    planned_event = row.get("planned_event")
                    collection_mode = (
                        row.get("collection_mode")
                        if row.get("collection_mode") in ALLOWED_COLLECTION_MODES
                        else "model_development"
                    )
                value = row.get("t")
                if isinstance(value, (int, float)):
                    if first_t is None:
                        first_t = float(value)
                    last_t = float(value)
                if row.get("stale"):
                    stale += 1
                legacy = str(row.get("ground_truth") or "unlabelled")
                if row.get("ground_truth_phase"):
                    label = str(row["ground_truth_phase"])
                elif legacy == "hazard":
                    # Migrate old mutually-exclusive labelling on read: the event
                    # occurred during the phase already in progress.
                    label = previous_label or "working"
                else:
                    label = legacy
                event = str(row.get("ground_truth_event") or (
                    "hazard" if legacy == "hazard" else "none"
                ))
                label_counts[label] = label_counts.get(label, 0) + 1
                event_counts[event] = event_counts.get(event, 0) + 1
                if label != "unlabelled" and label != previous_label:
                    sequence.append(label)
                previous_label = label
        duration_s = max(0.0, (last_t - first_t)) if first_t is not None and last_t is not None else 0.0
        rate_hz = samples / duration_s if duration_s > 0 else 0.0
        stale_ratio = stale / samples if samples else 1.0
        quality = self._quality(samples, duration_s, rate_hz, stale_ratio,
                                label_counts, sequence, invalid, event_counts,
                                planned_event)
        label_seconds = {
            label: round(count / rate_hz, 1) if rate_hz > 0 else 0.0
            for label, count in label_counts.items()
        }
        return {
            "session_id": session_id,
            "participant_id": participant_id,
            "trial_id": trial_id,
            "block_label": block_label,
            "controller_condition": controller_condition,
            "planned_event": planned_event,
            "collection_mode": collection_mode,
            "started_at": self._started_at(session_id, stat.st_mtime),
            "file_name": path.name,
            "samples": samples,
            "duration_s": round(duration_s, 1),
            "rate_hz": round(rate_hz, 1),
            "stale_percent": round(stale_ratio * 100, 2),
            "labels": label_seconds,
            "events": event_counts,
            "sequence": sequence,
            "quality": quality,
        }

    @staticmethod
    def _next_trial(runs: list[dict]) -> str:
        numbers = []
        for run in runs:
            match = re.fullmatch(r"T(\d+)", str(run.get("trial_id", "")), re.I)
            if match:
                numbers.append(int(match.group(1)))
        # Old dashboard versions allowed repeated T01 IDs. Count every saved
        # attempt as well as respecting the highest explicit trial number so
        # the next run can never reuse an occupied slot.
        number = max(max(numbers, default=0), len(runs)) + 1
        width = max(2, max((len(str(value)) for value in numbers), default=2))
        return f"T{number:0{width}d}"

    def catalog(self) -> dict:
        with self.lock:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            paths = [path for path in self.output_dir.glob("*.jsonl")
                     if not path.name.endswith(".events.jsonl")]
            live_keys = {str(path.resolve()) for path in paths}
            for key in list(self._cache):
                if key not in live_keys:
                    del self._cache[key]
            runs = []
            for path in paths:
                stat = path.stat()
                key = str(path.resolve())
                cached = self._cache.get(key)
                if cached is None or cached[0] != stat.st_size or cached[1] != stat.st_mtime_ns:
                    summary = self._summarize(path, stat)
                    self._cache[key] = (stat.st_size, stat.st_mtime_ns, summary)
                runs.append(dict(self._cache[key][2]))
            runs.sort(key=lambda row: row["started_at"], reverse=True)

            registered = self._load_registry()
            participant_ids = set(registered) | {run["participant_id"] for run in runs}
            participants = []
            for participant_id in sorted(participant_ids):
                participant_runs = [run for run in runs
                                    if run["participant_id"] == participant_id]
                profile = registered.get(participant_id, {})
                name = profile.get("name", "")
                collection_mode = profile.get("collection_mode")
                if collection_mode not in ALLOWED_COLLECTION_MODES:
                    run_modes = {run["collection_mode"] for run in participant_runs}
                    collection_mode = next(
                        (candidate for candidate in
                         ("participant_study", "qualification", "model_development")
                         if candidate in run_modes),
                        "model_development",
                    )
                for run in participant_runs:
                    run["participant_name"] = name
                participants.append({
                    "id": participant_id,
                    "name": name,
                    "created_at": profile.get("created_at"),
                    "collection_mode": collection_mode,
                    "run_count": len(participant_runs),
                    "good_run_count": sum(
                        run["quality"]["grade"] == "good" for run in participant_runs),
                    "next_trial": self._next_trial(participant_runs),
                })
            return {"participants": participants, "runs": runs}

    def next_trial(self, participant_id: object) -> str:
        value = safe_id(participant_id, "P00")
        data = self.catalog()
        for participant in data["participants"]:
            if participant["id"] == value:
                return participant["next_trial"]
        return "T01"

    def save_participant(self, name: object, participant_id: object = None,
                         collection_mode: object = "model_development") -> dict:
        with self.lock:
            mode = str(collection_mode or "").strip()
            if mode not in ALLOWED_COLLECTION_MODES:
                raise ValueError(
                    "Select participant study, qualification rehearsal, or model development"
                )
            clean_name = self._clean_name(name, mode)
            catalog = self.catalog()
            known_ids = {row["id"] for row in catalog["participants"]}
            if participant_id:
                value = safe_id(participant_id, "")
                if not value:
                    raise ValueError("Invalid participant ID")
            else:
                numbers = []
                prefix = "Q" if mode == "qualification" else "P"
                for value in known_ids:
                    match = re.fullmatch(rf"{prefix}(\d+)", value, re.I)
                    if match:
                        numbers.append(int(match.group(1)))
                value = f"{prefix}{max(numbers, default=0) + 1:02d}"
            registry = self._load_registry()
            registry[value] = {
                "id": value,
                "name": clean_name,
                "created_at": registry.get(value, {}).get("created_at")
                or datetime.now().isoformat(timespec="seconds"),
                "collection_mode": mode,
            }
            self._save_registry(registry)
            participant = next(row for row in self.catalog()["participants"]
                               if row["id"] == value)
            return {"message": f"Saved {value} — {clean_name}",
                    "participant": participant}


class DashboardState:
    def __init__(
        self, output_dir: Path, segment_id: int, model_path: Path | None = None,
        enable_research_output: bool = False,
    ) -> None:
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
        if model_path is not None and model_path.exists():
            self.hmm = load_upper_hmm(model_path)
            self.model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
            model_kind = ("pilot GMM-HMM" if isinstance(
                self.hmm.emissions, GaussianMixtureEmissions
            ) else "pilot Gaussian HMM")
            self.model_source = f"{model_kind} · {model_path.name}"
        else:
            self.hmm = fit_hmm(self.config)
            self.model_source = "synthetic baseline"
            self.model_sha256 = "synthetic-baseline"
        self.packet_times: deque[float] = deque(maxlen=240)
        self.packets = 0
        self.last_packet_wall: float | None = None
        self.position: list[float] | None = None
        self.xsens_position: list[float] | None = None
        self.xsens_frame: dict | None = None
        self.optitrack_stale = True
        self.optitrack_age_s: float | None = None
        self.feature: dict | None = None
        self.posterior: dict[str, float] = {}
        self.hmm_state: str | None = None
        self.active_controller = None
        self.controller_decision: dict | None = None
        # Research commands are logged but are not allowed to masquerade as a
        # safety-rated output. Physical application remains a separately
        # qualified collection-stage gate.
        self.controller_output_enabled = bool(enable_research_output)
        self.controller_output_applied = False
        self._last_controller_output_signature = None
        self.recording = False
        self.session_id: str | None = None
        self.participant_id: str | None = None
        self.trial_id: str | None = None
        self.block_label: str | None = None
        self.within_block_trial: int | None = None
        self.controller_condition: str | None = None
        self.planned_event: str | None = None
        self.collection_mode = "model_development"
        self.label = "unlabelled"
        self.event_label = "none"
        self.guided_step: int | None = None
        self.recording_path: str | None = None
        self.samples_written = 0
        self.mvn_recording_confirmed = False
        self.mvn_recording_reference: str | None = None
        self.motive_recording_reference: str | None = None
        self.video_recording_reference: str | None = None
        self.event_path: str | None = None
        self.manifest_path: str | None = None
        self.event_file = None
        self.sync_marker_count = 0
        self.optitrack_monitor: RigidBodyMonitor | None = None
        self.rig = None
        self.calibration_started: float | None = None
        self.file = None

    def on_sample(self, source_ts: float, position, tracked: bool, wall_time: float) -> None:
        self.bridge.on_sample(source_ts, position, tracked, wall_time)
        with self.lock:
            self.packets += 1
            self.last_packet_wall = wall_time
            self.packet_times.append(wall_time)

    def on_xsens_frame(self, frame: dict) -> None:
        """Retain the complete MXTP02 packet for the recording tick."""
        with self.lock:
            self.xsens_frame = frame

    def tick(self) -> None:
        now = time.monotonic()
        xsens_sample = self.bridge.tick(now)
        optitrack_sample = self.optitrack_bridge.tick(now)
        if xsens_sample is None:
            with self.lock:
                if self.recording and self.active_controller is not None:
                    decision = {
                        "status": "tracking_unavailable",
                        "command": "protective_stop",
                        "speed_fraction": 0.0,
                        "rule": "FAIL CLOSED: Xsens stream unavailable",
                        "output_applied": False,
                    }
                    self._apply_controller_output_locked(decision)
                    self.controller_decision = decision
            return
        # Absolute operator position comes from the tracked head rigid body in
        # robot-base coordinates. Xsens remains the articulated-motion source.
        sample = optitrack_sample
        frame = None if sample is None or sample.stale else self.extractor.push(
            sample.t, sample.position)
        posterior: dict[str, float] = {}
        state = None
        feature = None
        controller_decision = None
        if frame is not None:
            feature = asdict(frame)
            if self.active_controller is not None:
                decision = self.active_controller.decide(frame, robot_mode="ssm")
                controller_decision = asdict(decision)
                controller_decision["output_applied"] = False
                if decision.inferred_state in STATES:
                    posterior = {
                        name: float(decision.state_posterior[i])
                        for i, name in enumerate(STATES)
                    }
                    state = decision.inferred_state
            else:
                beliefs = self.hmm.step(frame.as_vector())
                posterior = {
                    name: float(beliefs[i]) for i, name in enumerate(STATES)
                }
                state = max(posterior, key=posterior.get)
        elif self.active_controller is not None:
            controller_decision = {
                "status": "tracking_unavailable",
                "command": "protective_stop",
                "speed_fraction": 0.0,
                "rule": "FAIL CLOSED: no fresh validated OptiTrack feature frame",
                "output_applied": False,
            }
        with self.lock:
            if controller_decision is not None:
                self._apply_controller_output_locked(controller_decision)
            self.xsens_position = [float(v) for v in xsens_sample.position]
            self.position = (None if sample is None else
                             [float(v) for v in sample.position])
            self.optitrack_stale = sample is None or sample.stale
            self.optitrack_age_s = None if sample is None else sample.age_s
            self.feature = feature
            self.posterior = posterior
            self.hmm_state = state
            self.controller_decision = controller_decision
            if self.recording and self.file is not None:
                rigid_bodies = {}
                if self.optitrack_monitor is not None:
                    rigid_bodies = {
                        str(rb_id): {
                            "position": list(body.position),
                            "rotation_xyzw": list(body.rotation_xyzw),
                            "source_time_s": body.source_time_s,
                            "age_s": round(body.age_s, 5),
                            "mean_error_m": body.mean_error_m,
                        }
                        for rb_id, body in self.optitrack_monitor.snapshot(now).items()
                    }
                robot_telemetry = (
                    self.rig.telemetry_snapshot(allow_connect=False)
                    if self.rig is not None else
                    {"available": False, "error": "rig not attached"}
                )
                record = {
                    "schema_version": 3,
                    "session_id": self.session_id,
                    "participant_id": self.participant_id,
                    "trial_id": self.trial_id,
                    "block_label": self.block_label,
                    "within_block_trial": self.within_block_trial,
                    "controller_condition": self.controller_condition,
                    "planned_event": self.planned_event,
                    "collection_mode": self.collection_mode,
                    "recorded_monotonic_s": round(now, 6),
                    "recorded_utc_time": datetime.now(timezone.utc).isoformat(),
                    "t": round(xsens_sample.t, 6),
                    "source_time_s": xsens_sample.motive_timestamp,
                    "position": self.position,
                    "optitrack_rigid_bodies": rigid_bodies,
                    "xsens_position": self.xsens_position,
                    "xsens_frame": self.xsens_frame,
                    "stale": self.optitrack_stale,
                    "age_s": (None if self.optitrack_age_s is None else
                              round(self.optitrack_age_s, 5)),
                    "features": feature,
                    "ground_truth": self.label,
                    "ground_truth_phase": self.label,
                    "ground_truth_event": self.event_label,
                    "hmm_state": state,
                    "hmm_posterior": posterior,
                    "controller_decision": controller_decision,
                    "controller_output_applied": self.controller_output_applied,
                    "sync_marker_count": self.sync_marker_count,
                    "model_source": self.model_source,
                    "model_sha256": self.model_sha256,
                    "mvn_native_recording_confirmed": self.mvn_recording_confirmed,
                    "mvn_native_recording_reference": self.mvn_recording_reference,
                    "motive_recording_reference": self.motive_recording_reference,
                    "video_recording_reference": self.video_recording_reference,
                    "robot_telemetry": robot_telemetry,
                }
                self.file.write(json.dumps(record, separators=(",", ":")) + "\n")
                self.file.flush()
                self.samples_written += 1

    def _apply_controller_output_locked(self, decision: dict) -> None:
        """Apply an opt-in research command and journal every command transition.

        This is deliberately named research output. The UR speed slider is not a
        safety-rated output and cannot close the independent safety-chain gate.
        """
        self.controller_output_applied = False
        if not self.controller_output_enabled or self.rig is None:
            decision["output_applied"] = False
            decision["output_status"] = (
                "disabled" if not self.controller_output_enabled else "rig_unavailable"
            )
            return
        result = self.rig.apply_research_speed_fraction(
            float(decision.get("speed_fraction", 0.0))
        )
        applied = bool(result.get("applied"))
        self.controller_output_applied = applied
        decision["output_applied"] = applied
        decision["output_status"] = result.get("status", "unknown")
        signature = (
            decision.get("command"), decision.get("speed_fraction"),
            applied, result.get("status"), result.get("error"),
        )
        if result.get("changed") or signature != self._last_controller_output_signature:
            self._journal_event_locked(
                "research_controller_command",
                command=decision.get("command"),
                speed_fraction=decision.get("speed_fraction"),
                applied=applied,
                status=result.get("status"),
                error=result.get("error"),
            )
        self._last_controller_output_signature = signature

    def start_session(self, participant: object, trial: object,
                      mvn_recording_confirmed: bool = False,
                      mvn_recording_reference: object = None,
                      block_label: object = None,
                      within_block_trial: object = None,
                      controller_condition: object = None,
                      planned_event: object = None,
                      collection_mode: object = "model_development",
                      motive_recording_reference: object = None,
                      video_recording_reference: object = None) -> dict:
        with self.lock:
            if self.recording:
                raise ValueError("A recording is already active")
            if not self.connected:
                raise ValueError("Xsens is not streaming yet")
            if self.optitrack_stale:
                raise ValueError("OptiTrack is not streaming a fresh head pose yet")
            segment_count = (0 if self.xsens_frame is None else
                             len(self.xsens_frame["segments"]))
            if segment_count < MVN_FULL_BODY_SEGMENTS:
                raise ValueError(
                    "Xsens full-body capture is incomplete: "
                    f"received {segment_count}/{MVN_FULL_BODY_SEGMENTS} "
                    "segments. Check MVN Position + Quaternion streaming."
                )
            if self.calibration_started is None:
                raise ValueError(
                    "Mark Xsens calibration complete before starting the run."
                )
            calibration_age = time.monotonic() - self.calibration_started
            if calibration_age > 300.0:
                raise ValueError(
                    f"Xsens calibration is {calibration_age:.0f}s old; recalibrate "
                    "and mark it complete again before starting."
                )
            if mvn_recording_confirmed is not True:
                raise ValueError(
                    "Confirm that native recording is active in MVN Analyze "
                    "before starting the participant run."
                )
            native_reference = str(mvn_recording_reference or "").strip()
            if len(native_reference) < 3:
                raise ValueError(
                    "Enter the visible Windows MVN recording filename or path."
                )
            motive_reference = str(motive_recording_reference or "").strip()
            video_reference = str(video_recording_reference or "").strip()
            reference_key = native_reference.replace("\\", "/").casefold()
            for prior_path in self.output_dir.glob("*.jsonl"):
                if prior_path.name.endswith(".events.jsonl"):
                    continue
                try:
                    with prior_path.open(encoding="utf-8") as prior_file:
                        prior_row = json.loads(next(
                            line for line in prior_file if line.strip()))
                except (OSError, StopIteration, json.JSONDecodeError):
                    continue
                prior_reference = str(
                    prior_row.get("mvn_native_recording_reference") or ""
                ).strip().replace("\\", "/").casefold()
                if prior_reference and prior_reference == reference_key:
                    raise ValueError(
                        "That native MVN filename/path was already used by "
                        f"{prior_path.name}; create a unique native recording."
                    )
            supplied_metadata = any(value is not None for value in (
                block_label, within_block_trial, controller_condition, planned_event
            ))
            block = str(block_label or "").strip().upper()
            controller = str(controller_condition or "").strip()
            event = str(planned_event or "").strip().lower()
            mode = str(collection_mode or "").strip()
            if mode not in ALLOWED_COLLECTION_MODES:
                raise ValueError(
                    "Select participant study, qualification rehearsal, or model development"
                )
            try:
                within = int(within_block_trial)
            except (TypeError, ValueError):
                within = 0
            if mode in {"participant_study", "qualification"} and not supplied_metadata:
                raise ValueError(
                    "Structured study and qualification runs require the assigned block, trial, "
                    "controller and event metadata"
                )
            if supplied_metadata:
                if block not in ALLOWED_BLOCK_LABELS:
                    raise ValueError("Select participant-facing block A, B or C")
                if within not in {1, 2, 3}:
                    raise ValueError("Select within-block trial 1, 2 or 3")
                if controller not in ALLOWED_CONTROLLER_CONDITIONS:
                    raise ValueError("Select the controller condition for this block")
                if event not in ALLOWED_PLANNED_EVENTS:
                    raise ValueError("Select clean, distractor or rapid intrusion")
            if mode in {"participant_study", "qualification"}:
                expected_controller, expected_event = assigned_study_slot(
                    participant, block, within
                )
                if controller != expected_controller or event != expected_event:
                    raise ValueError(
                        f"Assigned study slot is {block}{within}: "
                        f"{expected_controller}, {expected_event}"
                    )
                if not self.controller_output_enabled:
                    raise ValueError(
                        "Structured controller runs require the server to be launched "
                        "with --enable-research-speed-output"
                    )
                if self.model_sha256 == "synthetic-baseline":
                    raise ValueError(
                        "Structured controller runs require a real fitted model artifact"
                    )
                if len(motive_reference) < 3:
                    raise ValueError(
                        "Enter the visible Motive take filename for this structured run"
                    )
                if len(video_reference) < 3:
                    raise ValueError(
                        "Enter the visible consented video filename for this structured run"
                    )
            # Every recorded trial is an independent sequence. Do not let the
            # previous trial's HMM belief or derivative windows leak across it.
            self.hmm.reset()
            self.extractor.reset()
            self.feature = None
            self.posterior = {}
            self.hmm_state = None
            self.controller_decision = None
            self.controller_output_applied = False
            self._last_controller_output_signature = None
            implementation = CONTROLLER_IMPLEMENTATIONS.get(controller)
            self.active_controller = (
                build_controller(implementation, self.config, self.hmm)
                if implementation is not None else None
            )
            self.participant_id = safe_id(participant, "P00")
            self.trial_id = safe_id(trial, "T00")
            self.block_label = block or None
            self.within_block_trial = within or None
            self.controller_condition = controller or None
            self.planned_event = event or None
            self.collection_mode = mode
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.session_id = f"{self.participant_id}-{self.trial_id}-{stamp}-{uuid.uuid4().hex[:6]}"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            path = self.output_dir / f"{self.session_id}.jsonl"
            self.file = path.open("x", encoding="utf-8")
            self.recording_path = str(path.resolve())
            event_path = self.output_dir / f"{self.session_id}.events.jsonl"
            self.event_file = event_path.open("x", encoding="utf-8")
            self.event_path = str(event_path.resolve())
            self.samples_written = 0
            self.sync_marker_count = 0
            self.mvn_recording_confirmed = True
            self.mvn_recording_reference = native_reference[:500]
            self.motive_recording_reference = motive_reference[:500] or None
            self.video_recording_reference = video_reference[:500] or None
            self.label = "unlabelled"
            self.event_label = "none"
            self.guided_step = 0
            self.recording = True
            self._journal_event_locked("trial_started")
            return {
                "message": f"Recording {self.session_id}",
                "path": self.recording_path,
                "session_id": self.session_id,
                "participant_id": self.participant_id,
                "trial_id": self.trial_id,
                "block_label": self.block_label,
                "within_block_trial": self.within_block_trial,
                "controller_condition": self.controller_condition,
                "planned_event": self.planned_event,
                "collection_mode": self.collection_mode,
                "event_path": self.event_path,
                "mvn_native_recording_reference": self.mvn_recording_reference,
                "motive_recording_reference": self.motive_recording_reference,
                "video_recording_reference": self.video_recording_reference,
                "model_sha256": self.model_sha256,
                "controller_implementation": implementation,
                "controller_output_applied": self.controller_output_applied,
                "controller_output_enabled": self.controller_output_enabled,
            }

    def stop_session(self, outcome: str = "aborted") -> dict:
        with self.lock:
            if not self.recording:
                raise ValueError("No recording is active")
            if outcome not in {"completed", "aborted"}:
                raise ValueError("Trial outcome must be completed or aborted")
            self._journal_event_locked(
                f"trial_{outcome}", samples=self.samples_written,
                guided_step=self.guided_step,
            )
            manifest_path = Path(self.recording_path or "").with_suffix(".manifest.json")
            manifest = {
                "schema_version": 1,
                "session_id": self.session_id,
                "participant_id": self.participant_id,
                "trial_id": self.trial_id,
                "collection_mode": self.collection_mode,
                "block_label": self.block_label,
                "within_block_trial": self.within_block_trial,
                "controller_condition": self.controller_condition,
                "planned_event": self.planned_event,
                "outcome": outcome,
                "samples": self.samples_written,
                "dashboard_jsonl": self.recording_path,
                "event_jsonl": self.event_path,
                "native_mvn": self.mvn_recording_reference,
                "native_motive": self.motive_recording_reference,
                "consented_video": self.video_recording_reference,
                "robot_trace": "embedded in dashboard_jsonl.robot_telemetry",
                "model_sha256": self.model_sha256,
                "sync_marker_count": self.sync_marker_count,
                "controller_output_enabled": self.controller_output_enabled,
                "controller_output_last_applied": self.controller_output_applied,
                "saved_utc": datetime.now(timezone.utc).isoformat(),
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            self.manifest_path = str(manifest_path.resolve())
            self.recording = False
            if self.file is not None:
                self.file.close()
                self.file = None
            if self.event_file is not None:
                self.event_file.close()
                self.event_file = None
            self.label = "unlabelled"
            self.event_label = "none"
            self.guided_step = None
            self.active_controller = None
            self.controller_decision = None
            self.mvn_recording_confirmed = False
            self.mvn_recording_reference = None
            self.motive_recording_reference = None
            self.video_recording_reference = None
            return {
                "message": f"Saved {self.samples_written} samples",
                "path": self.recording_path,
                "manifest_path": self.manifest_path,
            }

    def _journal_event_locked(self, kind: str, **payload) -> None:
        if self.event_file is None:
            return
        row = {
            "schema_version": 1,
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "trial_id": self.trial_id,
            "block_label": self.block_label,
            "within_block_trial": self.within_block_trial,
            "controller_condition": self.controller_condition,
            "planned_event": self.planned_event,
            "collection_mode": self.collection_mode,
            "event": kind,
            "monotonic_time_s": round(time.monotonic(), 6),
            "utc_time": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        self.event_file.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.event_file.flush()

    def journal_event(self, kind: str, **payload) -> None:
        with self.lock:
            self._journal_event_locked(kind, **payload)

    def mark_sync_event(self) -> dict:
        with self.lock:
            if not self.recording:
                raise ValueError("Start recording before marking synchronization")
            self.sync_marker_count += 1
            self._journal_event_locked(
                "shared_sync_marker",
                marker_index=self.sync_marker_count,
                xsens_sample_counter=(
                    None if self.xsens_frame is None
                    else self.xsens_frame.get("sample_counter")
                ),
                optitrack_age_s=self.optitrack_age_s,
            )
            return {
                "message": f"Shared sync marker {self.sync_marker_count} recorded",
                "sync_marker_count": self.sync_marker_count,
            }

    def set_label(self, label: object) -> dict:
        value = str(label or "")
        if value == "hazard":
            with self.lock:
                if not self.recording:
                    raise ValueError("Start recording before applying labels")
                self.event_label = "hazard"
                self._journal_event_locked("manual_event_label", event_label="hazard")
            return {"message": "Ground-truth event: hazard"}
        if value not in ALLOWED_PHASE_LABELS:
            raise ValueError(f"Unknown label: {value}")
        with self.lock:
            if not self.recording:
                raise ValueError("Start recording before applying labels")
            self.label = value
            self.event_label = "none"
            self._journal_event_locked("manual_phase_label", phase=value)
        return {"message": f"Ground truth: {value}"}

    def begin_planned_event_window(self, source: str = "robot_lift") -> dict:
        """Open the assigned event while the robot is actually in motion."""
        with self.lock:
            if not self.recording:
                raise ValueError("Start recording before opening an event window")
            self.event_label = {
                "rapid intrusion": "hazard",
                "distractor": "distractor",
                "clean": "none",
            }.get(self.planned_event, "none")
            self._journal_event_locked(
                "planned_event_window_started",
                source=source,
                event_label=self.event_label,
            )
            return {"event_label": self.event_label, "source": source}

    def end_planned_event_window(self, source: str = "robot_lift") -> dict:
        with self.lock:
            if not self.recording:
                raise ValueError("No recording is active")
            previous = self.event_label
            self.event_label = "none"
            self._journal_event_locked(
                "planned_event_window_ended",
                source=source,
                event_label=previous,
            )
            return {"event_label": previous, "source": source}

    def advance_guided_protocol(self) -> dict:
        """Atomically advance the run instruction and its ground-truth label.

        The server owns this index so a page refresh cannot silently reset the
        experimenter to step one while an existing recording is still active.
        """
        with self.lock:
            if not self.recording:
                raise ValueError("Start guided recording before advancing the protocol")
            if self.guided_step is None:
                raise ValueError("This recording has no guided protocol state")
            if self.guided_step == 0 and self.sync_marker_count < 1:
                raise ValueError(
                    "Record the shared sync marker before starting the approach"
                )
            if self.guided_step >= len(GUIDED_PROTOCOL_LABELS) - 1:
                raise ValueError("Guided sequence is complete; stop and save the run")
            self.guided_step += 1
            self.label, self.event_label = GUIDED_PROTOCOL_LABELS[self.guided_step]
            self._journal_event_locked(
                "guided_step_changed", guided_step=self.guided_step,
                phase=self.label, event_label=self.event_label)
            return {
                "message": (
                    f"Guided step {self.guided_step + 1}: {self.label}"
                    + (f" + {self.event_label} event"
                       if self.event_label != "none" else "")
                ),
                "guided_step": self.guided_step,
                "label": self.label,
                "event_label": self.event_label,
            }

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
                "xsens_segment_count": (0 if self.xsens_frame is None else
                                         len(self.xsens_frame["segments"])),
                "optitrack_connected": not self.optitrack_stale,
                "optitrack_age_s": (None if self.optitrack_age_s is None else
                                    round(self.optitrack_age_s, 4)),
                "feature": self.feature,
                "posterior": self.posterior,
                "hmm_state": self.hmm_state,
                "model_source": self.model_source,
                "model_sha256": self.model_sha256,
                "recording": self.recording,
                "session_id": self.session_id,
                "participant_id": self.participant_id,
                "trial_id": self.trial_id,
                "block_label": self.block_label,
                "within_block_trial": self.within_block_trial,
                "controller_condition": self.controller_condition,
                "planned_event": self.planned_event,
                "collection_mode": self.collection_mode,
                "label": self.label,
                "event_label": self.event_label,
                "guided_step": self.guided_step,
                "guided_steps_total": len(GUIDED_PROTOCOL_LABELS),
                "recording_path": self.recording_path,
                "samples_written": self.samples_written,
                "calibration_elapsed_s": None if calibration_elapsed is None else round(calibration_elapsed, 1),
                "mvn_native_recording_reference": self.mvn_recording_reference,
                "motive_recording_reference": self.motive_recording_reference,
                "video_recording_reference": self.video_recording_reference,
                "event_path": self.event_path,
                "manifest_path": self.manifest_path,
                "controller_decision": self.controller_decision,
                "controller_output_applied": self.controller_output_applied,
                "controller_output_enabled": self.controller_output_enabled,
                "sync_marker_count": self.sync_marker_count,
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
        self._io = None              # RTDEIOInterface, opened only when opted in
        self._output_lock = threading.Lock()
        self._last_speed_fraction: float | None = None
        self._last_output_attempt_at = 0.0
        self._last_output_failure: dict | None = None
        self._poses = self._load_poses()
        self.fastening_complete = threading.Event()
        self.cycle_active = False
        self._status_lock = threading.Lock()
        self._status_refreshing = False
        self._status_updated = 0.0
        self._status_cache = {
            "gripper": {"error": "checking rig"},
            "robot": {"reachable": False, "error": "checking rig"},
            "pose": {"available": False, "error": "checking rig"},
        }

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
        # The ur-rtde constructor performs a long native connect while holding
        # the Python GIL. Probe the port with a short normal socket first so an
        # offline/booting robot cannot freeze every dashboard request.
        try:
            with socket.create_connection((self.robot_host, 30004), timeout=0.25):
                pass
        except OSError as exc:
            self._recv_error = f"RTDE port unavailable: {exc}"
            return None
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

    def telemetry_snapshot(self, *, allow_connect: bool = True) -> dict:
        """Read the current RTDE sample for trial logging without inventing defaults."""
        recv = self._receiver() if allow_connect else self._recv
        if recv is None:
            return {"available": False, "error": self._recv_error or "RTDE not connected"}
        getters = {
            "actual_tcp_pose": "getActualTCPPose",
            "actual_tcp_speed": "getActualTCPSpeed",
            "actual_q": "getActualQ",
            "actual_qd": "getActualQd",
            "speed_scaling": "getSpeedScaling",
            "target_speed_fraction": "getTargetSpeedFraction",
            "robot_mode": "getRobotMode",
            "safety_mode": "getSafetyMode",
            "runtime_state": "getRuntimeState",
        }
        result = {"available": True, "sampled_monotonic_s": round(time.monotonic(), 6)}
        try:
            for key, name in getters.items():
                fn = getattr(recv, name, None)
                if fn is None:
                    continue
                value = fn()
                if isinstance(value, (list, tuple)):
                    result[key] = [round(float(v), 6) for v in value]
                elif value is not None:
                    result[key] = float(value) if isinstance(value, float) else value
        except Exception as exc:
            self._recv = None
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        return result

    def apply_research_speed_fraction(self, speed_fraction: float) -> dict:
        """Write the UR speed slider for the research controller.

        This output is useful for experimental integration but is not a
        safety-rated stop channel. Port reachability is checked before importing
        the native RTDE client so an offline robot cannot freeze the ticker.
        """
        fraction = max(0.0, min(1.0, float(speed_fraction)))
        with self._output_lock:
            if (self._last_speed_fraction is not None and
                    abs(self._last_speed_fraction - fraction) < 1e-6):
                return {
                    "applied": True, "changed": False,
                    "status": "already_applied", "speed_fraction": fraction,
                }
            if self._io is None:
                now = time.monotonic()
                if (self._last_output_failure is not None and
                        now - self._last_output_attempt_at < 1.0):
                    return dict(self._last_output_failure)
                self._last_output_attempt_at = now
                try:
                    with socket.create_connection(
                        (self.robot_host, 30004), timeout=0.25
                    ):
                        pass
                    from rtde_io import RTDEIOInterface
                    self._io = RTDEIOInterface(self.robot_host)
                except Exception as exc:
                    self._io = None
                    self._last_output_failure = {
                        "applied": False, "changed": False,
                        "status": "rtde_io_unavailable",
                        "error": f"{type(exc).__name__}: {exc}",
                        "speed_fraction": fraction,
                    }
                    return dict(self._last_output_failure)
            try:
                applied = bool(self._io.setSpeedSlider(fraction))
            except Exception as exc:
                self._io = None
                return {
                    "applied": False, "changed": False,
                    "status": "write_failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "speed_fraction": fraction,
                }
            if applied:
                self._last_speed_fraction = fraction
                self._last_output_failure = None
            return {
                "applied": applied, "changed": applied,
                "status": "applied" if applied else "robot_rejected",
                "speed_fraction": fraction,
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
            if len(r) != 5 or any(not reply.strip() for reply in r):
                return {
                    "reachable": False,
                    "error": "Dashboard port opened but returned incomplete status",
                }
            return {"reachable": True, "robotmode": r[0], "safety": r[1],
                    "program_state": r[2], "loaded": r[3], "running": r[4]}
        except OSError as exc:
            return {"reachable": False, "error": str(exc)}

    def _refresh_status(self) -> None:
        """Refresh slow hardware health probes outside the HTTP request thread."""
        try:
            fresh = {
                "gripper": self.gripper_stats(),
                "robot": self.robot_status(),
                "pose": self.pose_status(),
            }
            with self._status_lock:
                self._status_cache = fresh
                self._status_updated = time.monotonic()
        finally:
            with self._status_lock:
                self._status_refreshing = False

    def status_snapshot(self, xsens: dict, max_age_s: float = 1.0) -> dict:
        """Return immediately from cache and refresh slow probes in the background.

        RTDE and Dashboard connections can each take several seconds to fail while
        the UR controller is booting. HTTP polling must never inherit that delay.
        """
        now = time.monotonic()
        with self._status_lock:
            if (
                not self._status_refreshing
                and now - self._status_updated > max_age_s
            ):
                self._status_refreshing = True
                threading.Thread(target=self._refresh_status, daemon=True).start()
            cached = dict(self._status_cache)
        return {
            **cached,
            "xsens": xsens,
            "cycle": {
                "active": self.cycle_active,
                "fastening_complete": self.fastening_complete.is_set(),
            },
        }

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

    def goto_pose(self, name: str, speed: float = 0.10) -> dict:
        """Move slowly to a taught joint pose through the RTDE controller.

        Discrete moves deliberately do not use the primary-interface socket.
        If a URScript injection is rejected before it starts, keeping that
        socket open can still occupy the robot's control channel indefinitely.
        RTDE gives us a synchronous success result and is always disconnected
        in ``finally``, so a failed move cannot wedge later controls.
        """
        pose = self._poses.get(name)
        if not pose or "q" not in pose:
            raise ValueError(f"Unknown taught pose: {name}. "
                             f"Have: {sorted(self._poses)}")
        spd = max(0.05, min(0.25, float(speed)))
        self.close_program_socket()

        robot = self.robot_status()
        if not robot.get("reachable"):
            raise ValueError("robot is unreachable")
        if "RUNNING" not in robot.get("robotmode", ""):
            raise ValueError("robot is not powered and brake-released")
        if "NORMAL" not in robot.get("safety", ""):
            raise ValueError(f"robot safety is not normal: {robot.get('safety')}")

        stats = self.gripper_stats(max_age_s=0.0)
        vacuum = (int(stats.get("vacuum_A_permille", 0)),
                  int(stats.get("vacuum_B_permille", 0)))
        if min(vacuum) < 500:
            raise ValueError(f"vacuum below motion threshold: {vacuum}")

        try:
            from rtde_control import RTDEControlInterface
        except ImportError as exc:
            raise ValueError("ur_rtde control module is unavailable") from exc

        control = None
        try:
            control = RTDEControlInterface(self.robot_host)
            moved = control.moveJ([float(v) for v in pose["q"]], spd, 0.15)
            if not moved:
                raise ValueError(f"move to {name} failed")
        finally:
            if control is not None:
                try:
                    control.stopJ(0.5)
                finally:
                    try:
                        control.stopScript()
                    finally:
                        control.disconnect()
        return {"pose": name, "q": pose["q"], "speed": spd,
                "vacuum": vacuum, "completed": True}

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


class GuidedRunController:
    """Coordinate labels and explicitly-confirmed rig actions for one run.

    A button press may perform a physical action, but no timer, inferred HMM
    state, or sensor classification can advance this state machine. Motion is
    permitted only after fresh tracking confirms the operator is beyond the
    configured yellow zone, the robot is RUNNING/NORMAL, and the panel grip is
    verified. The panel is released only at the taught low pose.
    """

    GRIP_MIN_PERMILLE = 500
    RELEASED_MAX_PERMILLE = 100
    POSE_TOLERANCE_RAD = 0.08
    ARM_MIN_DELAY_S = 0.75
    ARM_TIMEOUT_S = 5.0

    def __init__(self, state: DashboardState, rig: RigControl,
                 clock=time.monotonic) -> None:
        self.state = state
        self.rig = rig
        self.clock = clock
        self.lock = threading.Lock()
        self.armed_step: int | None = None
        self.armed_at = 0.0
        zones = state.config["zones"]
        red = zones["K"] * zones["T"] + zones["C"] + zones["Sa"]
        self.motion_clearance_m = (
            zones["yellow_margin"] * red + zones.get("hysteresis", 0.0)
        )

    def _clear_arm(self) -> None:
        self.armed_step = None
        self.armed_at = 0.0

    def _journal(self, kind: str, **payload) -> None:
        writer = getattr(self.state, "journal_event", None)
        if callable(writer):
            writer(kind, **payload)

    def arm_step(self) -> dict:
        """Arm one physical action; a later, separate request must execute it."""
        with self.lock:
            snap = self.state.snapshot()
            if not snap.get("recording") or snap.get("guided_step") is None:
                raise ValueError("No guided recording is active")
            step = int(snap["guided_step"])
            warning = PHYSICAL_STEP_WARNINGS.get(step)
            if warning is None:
                raise ValueError("This guided step does not perform a physical action")
            self.armed_step = step
            self.armed_at = self.clock()
            return {
                "message": f"ARMED: {warning} Press again within five seconds.",
                "armed_step": step,
                "expires_in_s": self.ARM_TIMEOUT_S,
            }

    def _require_armed(self, step: int) -> None:
        if step not in PHYSICAL_STEP_WARNINGS:
            self._clear_arm()
            return
        if self.armed_step != step:
            self._clear_arm()
            raise ValueError("Physical action is not armed; press once, then press again")
        elapsed = self.clock() - self.armed_at
        if elapsed < self.ARM_MIN_DELAY_S:
            raise ValueError("Confirmation was too fast; wait, then press again")
        if elapsed > self.ARM_TIMEOUT_S:
            self._clear_arm()
            raise ValueError("Physical-action confirmation expired; press once to arm again")
        self._clear_arm()

    def _require_robot_ready(self) -> dict:
        robot = self.rig.robot_status()
        if not robot.get("reachable"):
            raise ValueError("Robot is unreachable")
        if "RUNNING" not in robot.get("robotmode", ""):
            raise ValueError("Robot is not powered and brake-released")
        if "NORMAL" not in robot.get("safety", ""):
            raise ValueError(f"Robot safety is not normal: {robot.get('safety')}")
        return robot

    def _require_operator_clear(self) -> float:
        snap = self.state.snapshot()
        if not snap.get("connected") or snap.get("stale"):
            raise ValueError("Xsens is not fresh; robot motion is blocked")
        if not snap.get("optitrack_connected"):
            raise ValueError("OptiTrack is not fresh; robot motion is blocked")
        feature = snap.get("feature") or {}
        distance = feature.get("d")
        if distance is None:
            raise ValueError("Operator separation is unavailable; robot motion is blocked")
        distance = float(distance)
        if distance < self.motion_clearance_m:
            raise ValueError(
                f"Operator is {distance:.2f} m from the robot; move beyond "
                f"{self.motion_clearance_m:.2f} m before confirming cell clear"
            )
        return distance

    def _require_pose(self, name: str) -> dict:
        target = self.rig._poses.get(name, {}).get("q")
        pose = self.rig.pose_status()
        current = pose.get("q")
        if not target or not pose.get("available") or not current:
            raise ValueError(f"Cannot verify the robot is at {name}")
        error = max(abs(float(a) - float(b)) for a, b in zip(current, target))
        if error > self.POSE_TOLERANCE_RAD:
            raise ValueError(
                f"Robot is not at the required {name} pose "
                f"(joint error {error:.3f} rad)"
            )
        return pose

    def start(self, participant: object, trial: object,
              mvn_recording_confirmed: bool = False,
              mvn_recording_reference: object = None,
              block_label: object = None,
              within_block_trial: object = None,
              controller_condition: object = None,
              planned_event: object = None,
              collection_mode: object = "model_development",
              motive_recording_reference: object = None,
              video_recording_reference: object = None) -> dict:
        """Preflight the low, released rig before opening a guided recording."""
        with self.lock:
            self._clear_arm()
            self._require_robot_ready()
            self._require_operator_clear()
            self._require_pose("pose1_low")
            stats = self.rig.gripper_stats(max_age_s=0.0)
            vacuum = (int(stats.get("vacuum_A_permille", 0)),
                      int(stats.get("vacuum_B_permille", 0)))
            pump = int(stats.get("pump_rpm", 0))
            if max(vacuum) > self.RELEASED_MAX_PERMILLE or pump > 100:
                raise ValueError(
                    "Guided run requires the arm low with suction off; "
                    "use the manual recovery controls to release the current panel first"
                )
            metadata = (block_label, within_block_trial,
                        controller_condition, planned_event)
            if any(value is not None for value in metadata):
                result = self.state.start_session(
                    participant, trial, mvn_recording_confirmed,
                    mvn_recording_reference, block_label, within_block_trial,
                    controller_condition, planned_event, collection_mode,
                    motive_recording_reference, video_recording_reference)
            else:
                result = self.state.start_session(
                    participant, trial, mvn_recording_confirmed,
                    mvn_recording_reference)
            return {**result, "preflight": {
                "pose": "pose1_low", "vacuum": vacuum,
                "operator_clearance_m": self.motion_clearance_m,
            }}

    def complete_step(self, vacuum: int = 60) -> dict:
        """Complete the visible instruction, perform its action, then advance."""
        with self.lock:
            snap = self.state.snapshot()
            if not snap.get("recording") or snap.get("guided_step") is None:
                raise ValueError("No guided recording is active")
            step = int(snap["guided_step"])
            self._require_armed(step)
            if step == 0 and int(snap.get("sync_marker_count", 0)) < 1:
                raise ValueError(
                    "Record the shared sync marker before starting the approach"
                )
            action: dict | None = None
            self._journal("guided_action_requested", guided_step=step)

            if step == 2:  # panel aligned at the low gripper
                action = self.rig.gripper_action("grip", "BOTH", int(vacuum))
                stats = action.get("stats", {})
                seal = (int(stats.get("vacuum_A_permille", 0)),
                        int(stats.get("vacuum_B_permille", 0)))
                if not action.get("ok") or min(seal) < self.GRIP_MIN_PERMILLE:
                    # Never leave a half-sealed panel looking ready to lift.
                    self.rig.gripper_action("release", "BOTH", 0)
                    raise ValueError(f"Panel grip was not verified: vacuum {seal}")
            elif step == 3:  # participant has retreated; lift the panel
                distance = self._require_operator_clear()
                self._require_robot_ready()
                # Robot travel is not a human-motion training state. Exclude
                # the blocking motion interval rather than recording a long
                # stationary segment as "retreating".
                self.state.set_label("unlabelled")
                self.state.begin_planned_event_window(source="robot_lift")
                try:
                    action = self.rig.goto_pose("pose2_top")
                except Exception:
                    self.state.end_planned_event_window(source="robot_lift")
                    self.state.set_label("retreating")
                    raise
                self.state.end_planned_event_window(source="robot_lift")
                action["operator_distance_m"] = round(distance, 3)
            elif step == 8:  # participant has retreated after the overhead task
                distance = self._require_operator_clear()
                self._require_robot_ready()
                self.state.set_label("unlabelled")
                try:
                    action = self.rig.goto_pose("pose1_low")
                except Exception:
                    self.state.set_label("retreating")
                    raise
                action["operator_distance_m"] = round(distance, 3)
            elif step == 9:  # arm is stationary low and panel is manually supported
                self._require_robot_ready()
                self._require_pose("pose1_low")
                action = self.rig.gripper_action("release", "BOTH", 0)
                if not action.get("ok"):
                    raise ValueError(
                        f"Panel release failed: {action.get('error', 'unknown error')}"
                    )
                saved = self.state.stop_session(outcome="completed")
                return {
                    **saved,
                    "completed": True,
                    "action": action,
                }

            advanced = self.state.advance_guided_protocol()
            if action is not None:
                self._journal(
                    "guided_action_completed", guided_step=step,
                    action_summary=str(action)[:500])
            return {**advanced, "action": action}


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
    guided: GuidedRunController
    catalog: RunCatalog
    allow_remote_control = False
    control_key = ""
    _form_status_cache: tuple[float, dict] | None = None

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

    @classmethod
    def _form_access_status(cls) -> dict:
        now = time.monotonic()
        if cls._form_status_cache is not None:
            checked_at, payload = cls._form_status_cache
            if now - checked_at < 60.0:
                return payload
        forms = {}
        for stage, url in PARTICIPANT_FORM_URLS.items():
            request = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 HRC-form-preflight"}
            )
            try:
                cafile = "/etc/ssl/cert.pem"
                context = ssl.create_default_context(
                    cafile=cafile if Path(cafile).is_file() else None
                )
                with urllib.request.urlopen(
                    request, timeout=6, context=context
                ) as response:
                    status = int(response.status)
                forms[stage] = {
                    "accessible_without_login": status == 200,
                    "responder_route_available": status == 200,
                    "requires_monash_login": False,
                    "http_status": status,
                }
            except urllib.error.HTTPError as exc:
                # Monash-owned Forms return 401/403 to this server-side probe
                # because it has no participant Google session. That is an
                # authentication requirement, not evidence of a broken form.
                login_required = int(exc.code) in {401, 403}
                forms[stage] = {
                    "accessible_without_login": False,
                    "responder_route_available": login_required,
                    "requires_monash_login": login_required,
                    "http_status": int(exc.code),
                    "error": str(exc.reason),
                }
            except Exception as exc:
                forms[stage] = {
                    "accessible_without_login": False,
                    "responder_route_available": False,
                    "requires_monash_login": False,
                    "http_status": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        payload = {
            "checked_utc": datetime.now(timezone.utc).isoformat(),
            "forms": forms,
            "all_accessible_without_login": all(
                item["accessible_without_login"] for item in forms.values()
            ),
            "all_responder_routes_available": all(
                item["responder_route_available"] for item in forms.values()
            ),
        }
        cls._form_status_cache = (now, payload)
        return payload

    @classmethod
    def _form_completion_status(cls, query: dict[str, list[str]]) -> dict:
        """Check the privacy-minimal Apps Script bridge for one form handoff.

        The bridge returns only whether an anonymous participant code exists in
        the relevant response tab. Questionnaire answers never pass through the
        dashboard service.
        """
        endpoint = os.environ.get("HRC_FORM_COMPLETION_URL", "").strip()
        if not endpoint:
            endpoint_file = Path("data/xsens/.form_completion_url")
            if endpoint_file.is_file():
                endpoint = endpoint_file.read_text(encoding="utf-8").strip()
        token = os.environ.get("HRC_FORM_COMPLETION_TOKEN", "").strip()
        if not token:
            token_file = Path("data/xsens/.control_key")
            if token_file.is_file():
                token = token_file.read_text(encoding="utf-8").strip()
        participant_id = safe_id((query.get("participant_id") or [""])[0], "")
        stage = (query.get("stage") or [""])[0]
        block = (query.get("block") or [""])[0].upper()
        if stage not in PARTICIPANT_FORM_URLS or not participant_id:
            raise ValueError("participant_id and a valid form stage are required")
        if stage == "block" and block not in ALLOWED_BLOCK_LABELS:
            raise ValueError("block must be A, B or C for block feedback")
        if not endpoint or not token:
            return {
                "tracking_configured": False,
                "tracking_available": False,
                "submitted": False,
                "participant_id": participant_id,
                "stage": stage,
                "block": block or None,
            }
        if not endpoint.startswith("https://"):
            raise ValueError("HRC_FORM_COMPLETION_URL must use HTTPS")
        params = urllib.parse.urlencode({
            "participant_id": participant_id,
            "stage": stage,
            "block": block,
            "token": token,
        })
        separator = "&" if "?" in endpoint else "?"
        request = urllib.request.Request(
            f"{endpoint}{separator}{params}",
            headers={"User-Agent": "HRC-dashboard-form-completion/1.0"},
        )
        try:
            cafile = "/etc/ssl/cert.pem"
            context = ssl.create_default_context(
                cafile=cafile if Path(cafile).is_file() else None
            )
            with urllib.request.urlopen(request, timeout=6, context=context) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("ok") is not True:
                raise ValueError(str(payload.get("error") or "completion bridge rejected request"))
            return {
                "tracking_configured": True,
                "tracking_available": True,
                "submitted": payload.get("submitted") is True,
                "participant_id": participant_id,
                "stage": stage,
                "block": block or None,
                "checked_utc": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            return {
                "tracking_configured": True,
                "tracking_available": False,
                "submitted": False,
                "participant_id": participant_id,
                "stage": stage,
                "block": block or None,
                "error": f"{type(exc).__name__}: {exc}",
            }

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
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/api/status":
            self._json(self.state.snapshot())
        elif path == "/api/rig":
            self._json(self.rig.status_snapshot(self.state.snapshot()))
        elif path == "/api/catalog":
            self._json(self.catalog.catalog())
        elif path == "/api/forms/status":
            self._json(self._form_access_status())
        elif path == "/api/forms/completion":
            self._json(self._form_completion_status(query))
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
            rig_paths = {
                "/api/gripper", "/api/robot", "/api/demo", "/api/cycle",
                "/api/xsens/reset", "/api/protocol/start", "/api/protocol/arm",
                "/api/protocol/complete", "/api/sync",
            }
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
                elif self.path == "/api/protocol/start":
                    participant_id = body.get("participant_id")
                    result = self.guided.start(
                        participant_id, self.catalog.next_trial(participant_id),
                        body.get("mvn_recording_confirmed") is True,
                        body.get("mvn_recording_reference"),
                        body.get("block_label"), body.get("within_block_trial"),
                        body.get("controller_condition"), body.get("planned_event"),
                        body.get("collection_mode", "model_development"),
                        body.get("motive_recording_reference"),
                        body.get("video_recording_reference"))
                elif self.path == "/api/protocol/arm":
                    result = self.guided.arm_step()
                elif self.path == "/api/protocol/complete":
                    result = self.guided.complete_step(int(body.get("vacuum", 60)))
                elif self.path == "/api/sync":
                    result = self.state.mark_sync_event()
                else:
                    if body.get("action") == "start":
                        result = self.rig.demo_start(int(body.get("vacuum", 60)))
                    else:
                        result = self.rig.demo_stop()
                return self._json(result)
            if remote and not self.allow_remote_control:
                return self._json({"error": "Remote browsers are view-only"}, 403)
            if self.path == "/api/session/start":
                result = self.state.start_session(
                    body.get("participant_id"), body.get("trial_id"),
                    body.get("mvn_recording_confirmed") is True,
                    body.get("mvn_recording_reference"))
            elif self.path == "/api/session/stop":
                result = self.state.stop_session(outcome="aborted")
            elif self.path == "/api/label":
                result = self.state.set_label(body.get("label"))
            elif self.path == "/api/protocol/advance":
                result = self.state.advance_guided_protocol()
            elif self.path == "/api/calibration/mark":
                result = self.state.mark_calibrated()
            elif self.path == "/api/participants":
                result = self.catalog.save_participant(
                    body.get("name"), body.get("participant_id"),
                    body.get("collection_mode", "model_development"))
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
    parser.add_argument(
        "--enable-research-speed-output", action="store_true",
        help=(
            "apply controller speed fractions through the UR RTDE speed slider; "
            "this is research integration, not a safety-rated stop channel"
        ),
    )
    parser.add_argument(
        "--model",
        default="data/models/pilot_hmm.json",
        help="pilot-fitted HMM JSON (synthetic cold start when absent)",
    )
    args = parser.parse_args()

    state = DashboardState(
        Path(args.out), args.segment, Path(args.model),
        enable_research_output=args.enable_research_speed_output,
    )
    catalog = RunCatalog(Path(args.out))
    listener = XsensListener(
        state, port=args.udp_port, segment_id=args.segment,
        on_frame=state.on_xsens_frame)
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
    state.optitrack_monitor = optitrack_monitor
    state.rig = rig
    guided = GuidedRunController(state, rig)
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
    ApiHandler.guided = guided
    ApiHandler.catalog = catalog
    ApiHandler.control_key = control_key
    ApiHandler.allow_remote_control = args.allow_remote_control
    host = "0.0.0.0" if args.share else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.http_port), ApiHandler)
    # A slow hardware socket probe must not keep the process alive on shutdown.
    server.daemon_threads = True
    print(f"Dashboard sensor service: http://{host}:{args.http_port}")
    print(f"RIG CONTROL PAGE: http://<this-mac-ip>:{args.http_port}/control?k={control_key}")
    print(f"Xsens MVN target: UDP {args.udp_port} · Position + Quaternion · segment {args.segment}")
    print(f"Recordings: {Path(args.out).resolve()}")
    print(f"Model: {state.model_source}")
    print(
        "Research speed output: "
        + ("ENABLED (not safety-rated)" if state.controller_output_enabled else "disabled")
    )
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
