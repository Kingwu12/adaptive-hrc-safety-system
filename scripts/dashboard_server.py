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
from dataclasses import asdict, replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vg10 import VG10  # noqa: E402

from hrc_safety.analysis import build_controller, fit_hmm  # noqa: E402
from hrc_safety.config import load_config  # noqa: E402
from hrc_safety.features import FeatureExtractor  # noqa: E402
from hrc_safety.experiment_diagnostics import (ControllerComparison, EventExposure, model_health,
                                             release_fingerprint, live_tcp_position)  # noqa: E402
from hrc_safety.work_locations import WorkLocationVisits  # noqa: E402
from hrc_safety.simulated_drilling import SimulatedDrilling, aligned_hands  # noqa: E402
from hrc_safety.body_tracking import HelmetBodyTracker  # noqa: E402
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

SERVICE_CONTRACT = "adaptive-hrc-lab-backend-v1"


def service_identity() -> dict:
    """Identify the exact backend process and source file serving this API."""
    source = Path(__file__).resolve()
    return {
        "contract": SERVICE_CONTRACT,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
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
        self._scan_lock = threading.RLock()
        self._cache: dict[str, tuple[int, tuple[int, int], dict]] = {}

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
                 planned_event: str | None = None, *, automatic=False,
                 completed=False) -> dict:
        score = 100
        issues: list[str] = []
        missing = [] if automatic else [label for label in cls.REQUIRED_LABELS
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
        if not automatic and tuple(sequence) != cls.EXPECTED_SEQUENCE:
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
        if rate_hz > 0 and not automatic:
            short = [label for label in cls.REQUIRED_LABELS
                     if 0 < label_counts.get(label, 0) / rate_hz < 2.0]
            if short:
                score -= 10
                issues.append("too little " + ", ".join(short) + " data")
        if invalid_rows:
            score -= 10
            issues.append(f"{invalid_rows} unreadable samples")
        if automatic and not completed:
            score = 0
            issues.append("automatic cycle was not completed; inspect before repeating")
        score = max(0, score)
        if score >= 85 and not missing:
            grade, label = "good", "GOOD"
        elif score >= 60:
            grade, label = "review", "REVIEW"
        else:
            grade, label = "repeat", "REPEAT"
        if not issues:
            issues.append("automatic cycle completed with stable capture; human labels require video annotation" if automatic
                          else "all phases captured in order with stable tracking")
        return {"grade": grade, "label": label, "score": score, "reasons": issues}

    def _summarize(self, path: Path, stat) -> dict:
        samples = stale = invalid = 0
        first_t = last_t = None
        session_id = path.stem
        participant_id = "P00"
        trial_id = "T00"
        block_label = controller_condition = planned_event = None
        within_block_trial = None
        collection_mode = "model_development"
        execution_mode = "operator_confirmed"
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
                    execution_mode = str(row.get("execution_mode") or "operator_confirmed")
                    session_id = str(row.get("session_id") or path.stem)
                    participant_id = safe_id(row.get("participant_id"), "P00")
                    trial_id = safe_id(row.get("trial_id"), "T00")
                    block_label = row.get("block_label")
                    within_block_trial = row.get("within_block_trial")
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
        completed = False
        try:
            manifest = json.loads(path.with_suffix(".manifest.json").read_text())
            completed = (manifest.get("session_id") == session_id
                         and manifest.get("outcome") == "completed"
                         and manifest.get("execution_mode", "operator_confirmed") == execution_mode)
        except (OSError, ValueError):
            pass
        quality = self._quality(samples, duration_s, rate_hz, stale_ratio,
                                label_counts, sequence, invalid, event_counts,
                                planned_event, automatic=execution_mode == "automatic",
                                completed=completed)
        label_seconds = {
            label: round(count / rate_hz, 1) if rate_hz > 0 else 0.0
            for label, count in label_counts.items()
        }
        return {
            "session_id": session_id,
            "participant_id": participant_id,
            "trial_id": trial_id,
            "block_label": block_label,
            "within_block_trial": within_block_trial,
            "controller_condition": controller_condition,
            "planned_event": planned_event,
            "collection_mode": collection_mode,
            "started_at": self._started_at(session_id, stat.st_mtime),
            "execution_mode": execution_mode,
            "completed": completed,
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
        with self._scan_lock:
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
                manifest_path = path.with_suffix(".manifest.json")
                stamp = (stat.st_mtime_ns,
                         manifest_path.stat().st_mtime_ns if manifest_path.exists() else 0)
                if cached is None or cached[0] != stat.st_size or cached[1] != stamp:
                    summary = None
                    manifest = {}
                    if manifest_path.exists():
                        try:
                            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                            candidate = manifest.get("catalog_summary")
                            if (isinstance(candidate, dict)
                                    and candidate.get("file_name") == path.name
                                    and candidate.get("session_id") == path.stem):
                                summary = candidate
                        except (OSError, ValueError, TypeError):
                            pass
                    cache_path = path.with_suffix(".catalog.json")
                    if summary is None and cache_path.exists():
                        try:
                            payload = json.loads(cache_path.read_text(encoding="utf-8"))
                            if (payload.get("source_size") == stat.st_size
                                    and payload.get("source_stamp") == list(stamp)
                                    and isinstance(payload.get("summary"), dict)):
                                summary = payload["summary"]
                        except (OSError, ValueError, TypeError):
                            pass
                    if summary is None:
                        summary = self._summarize(path, stat)
                        payload = {
                            "source_size": stat.st_size,
                            "source_stamp": list(stamp),
                            "summary": summary,
                        }
                        temporary = cache_path.with_suffix(".json.tmp")
                        try:
                            temporary.write_text(json.dumps(payload), encoding="utf-8")
                            temporary.replace(cache_path)
                        except OSError:
                            try:
                                temporary.unlink(missing_ok=True)
                            except OSError:
                                pass
                    # Capture grades do not prove completion. Derive eligibility
                    # from the manifest even for summaries cached by old versions;
                    # leave historical capture grades and source files untouched.
                    summary = dict(summary)
                    summary["completed"] = (
                        manifest.get("session_id") == path.stem
                        and manifest.get("outcome") == "completed"
                    )
                    self._cache[key] = (stat.st_size, stamp, summary)
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
            registry = self._load_registry()
            known_ids = set(registry)
            # Allocating a code needs IDs, not a quality scan of every frame.
            # Read recording headers so legacy, unregistered IDs remain reserved.
            for path in self.output_dir.glob("*.jsonl"):
                if path.name.endswith(".events.jsonl"):
                    continue
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            row = json.loads(line)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        known_ids.add(safe_id(row.get("participant_id"), "P00"))
                        break
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
            registry[value] = {
                "id": value,
                "name": clean_name,
                "created_at": registry.get(value, {}).get("created_at")
                or datetime.now().isoformat(timespec="seconds"),
                "collection_mode": mode,
            }
            self._save_registry(registry)
            if participant_id:
                participant = next(row for row in self.catalog()["participants"]
                                   if row["id"] == value)
            else:
                participant = {**registry[value], "run_count": 0,
                               "good_run_count": 0, "next_trial": "T01"}
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
        self.robot_transform = extrinsics
        self.body_tracker = HelmetBodyTracker()
        self.body_tracking = {"available": False, "reason": "Waiting for helmet and Xsens body"}
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
        self.model_health = model_health(self.hmm, features["sample_rate_hz"])
        self.controller_comparison = None
        self.shadow_controllers = None
        self.study_release = None
        self.runtime_release = release_fingerprint(
            Path(__file__).resolve().parents[1], self.model_sha256, self.config)
        self.service = service_identity()
        self.event_exposure = EventExposure(self.config)
        self.geometry_reference = {"source": "unavailable", "tcp_position_m": None}
        self.pipeline_error = None
        self.feature_status = "unavailable"
        self.packets = 0
        self.last_packet_wall: float | None = None
        self.position: list[float] | None = None
        self.xsens_position: list[float] | None = None
        self.xsens_frame: dict | None = None
        self.xsens_frame_wall: float | None = None
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
        self.capture_mode = "automatic_streams"
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
        self.execution_mode = "operator_confirmed"
        self.automation_contract: dict | None = None
        self.controller_updated_at = 0.0
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
        self._catalog_first_t: float | None = None
        self._catalog_last_t: float | None = None
        self._catalog_stale = 0
        self._catalog_label_counts: dict[str, int] = {}
        self._catalog_event_counts: dict[str, int] = {}
        self._catalog_sequence: list[str] = []
        self._catalog_previous_label: str | None = None
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
            self.xsens_frame_wall = time.monotonic()

    def tick(self) -> None:
        # Starting/stopping a trial must not race with inference or sample writes.
        with self.lock:
            if self.pipeline_error is not None:
                self._hold_pipeline_fault()
                return
            try:
                self._tick_locked()
            except Exception as exc:
                self.pipeline_error = f"{type(exc).__name__}: {exc}"
                self._hold_pipeline_fault()

    def _hold_pipeline_fault(self):
        """Keep a failed capture/inference pipeline visibly latched at zero."""
        self.body_tracking = {"available": False, "reason": "Capture pipeline fault"}
        self.feature = None
        self.feature_status = "pipeline_fault"
        self.controller_comparison = None
        self.event_exposure.moving = False
        decision = {"command":"protective_stop", "speed_fraction":0.0,
                    "rule":"FAIL CLOSED: capture/controller pipeline failed; restart service",
                    "output_applied":False}
        self.controller_decision = decision
        if self.recording:
            try:
                self._apply_controller_output_locked(decision)
            except Exception:
                # The original error remains visible even if the output or its
                # journal also fails (for example, a full recording disk).
                decision['output_applied'] = False
                decision['output_status'] = 'pipeline_fault_output_unconfirmed'

    def _tick_locked(self) -> None:
        now = time.monotonic()
        xsens_sample = self.bridge.tick(now)
        optitrack_sample = self.optitrack_bridge.tick(now)
        if xsens_sample is None:
            with self.lock:
                self.feature = None
                self.body_tracker.reset()
                self.body_tracking = {"available": False, "reason": "Xsens unavailable"}
                self.feature_status = "unavailable"
                self.geometry_reference = {"source": "unavailable", "tcp_position_m": None}
                self.event_exposure.moving = False
                self.extractor.reset()
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
                    self.controller_comparison = None
                    self.controller_updated_at = now
            return
        # Absolute operator position comes from the tracked head rigid body in
        # robot-base coordinates. Xsens remains the articulated-motion source.
        robot_telemetry = (self.rig.telemetry_snapshot(allow_connect=False)
                           if self.rig is not None else {"available": False})
        tcp = live_tcp_position(robot_telemetry)
        if tcp is not None:
            self.extractor.set_tcp(tcp)
            self.geometry_reference = {"source": "live_rtde_tcp", "tcp_position_m": tcp,
                                       "source_timestamp_s": robot_telemetry['source_timestamp_s']}
        elif self.rig is None and self.collection_mode == "model_development":
            # Explicit offline development only. Never substitute a configured
            # reference for a missing live robot pose in a structured run.
            tcp = list(self.config['scenario']['tcp_position'])
            self.extractor.set_tcp(tcp)
            self.geometry_reference = {"source": "configured_development_reference", "tcp_position_m": tcp}
        else:
            self.geometry_reference = {"source": "unavailable", "tcp_position_m": None}
        bodies = {} if self.optitrack_monitor is None else self.optitrack_monitor.snapshot(now)
        self.body_tracking = self.body_tracker.update(
            self.xsens_frame, None if 1 not in bodies else asdict(bodies[1]),
            xsens_age_s=None if self.xsens_frame_wall is None else now - self.xsens_frame_wall,
            config=self.config.get("helmet_body"), robot_transform=self.robot_transform, tcp=tcp)
        sample = optitrack_sample
        if sample is None or sample.stale or xsens_sample.stale or tcp is None:
            self.extractor.reset()
            frame = None
            self.feature_status = "unavailable"
        else:
            frame = self.extractor.push(sample.t, sample.position)
            self.feature_status = "ready" if frame is not None else "warming_up"
        if frame is not None and self.body_tracking.get("features_ready"):
            frame = replace(frame, body_features=self.body_tracking["features"],
                            body_geometry=self.body_tracking.get("body_geometry"))
        body_required = self.config.get("helmet_body", {}).get("enabled") or any(
            name.startswith("body.") for name in self.hmm.feature_order)
        if body_required and not self.body_tracking.get("body_geometry"):
            frame = None
            self.feature_status = "warming_up" if self.body_tracking.get("available") else "unavailable"
        posterior: dict[str, float] = {}
        state = None
        feature = None
        controller_decision = None
        comparison = None
        if frame is not None:
            feature = asdict(frame)
            if self.active_controller is not None:
                decision = self.active_controller.decide(frame, robot_mode="ssm")
                controller_decision = asdict(decision)
                controller_decision["output_applied"] = False
                if self.shadow_controllers is not None:
                    comparison = self.shadow_controllers.decide(frame)
                if decision.inferred_state in STATES:
                    posterior = {
                        name: float(decision.state_posterior[i])
                        for i, name in enumerate(STATES)
                    }
                    state = decision.inferred_state
            else:
                beliefs = self.hmm.step(frame.as_vector(self.hmm.feature_order))
                posterior = {
                    name: float(beliefs[i]) for i, name in enumerate(STATES)
                }
                state = max(posterior, key=posterior.get)
        elif self.active_controller is not None:
            controller_decision = {
                "status": "tracking_unavailable",
                "command": "protective_stop",
                "speed_fraction": 0.0,
                "rule": "FAIL CLOSED: fresh Xsens, OptiTrack and live robot geometry are required",
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
            self.controller_comparison = comparison
            self.controller_updated_at = now
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
                self.event_exposure.observe(None if frame is None else asdict(frame.for_control()), robot_telemetry,
                                            self.event_label in {"hazard", "distractor"})
                record = {
                    "schema_version": 3,
                    "capture_mode": self.capture_mode,
                    "session_id": self.session_id,
                    "participant_id": self.participant_id,
                    "trial_id": self.trial_id,
                    "block_label": self.block_label,
                    "within_block_trial": self.within_block_trial,
                    "controller_condition": self.controller_condition,
                    "planned_event": self.planned_event,
                    "collection_mode": self.collection_mode,
                    "recorded_monotonic_s": round(now, 6),
                    "execution_mode": self.execution_mode,
                    "recorded_utc_time": datetime.now(timezone.utc).isoformat(),
                    "t": round(xsens_sample.t, 6),
                    "source_time_s": xsens_sample.motive_timestamp,
                    "position": self.position,
                    "optitrack_rigid_bodies": rigid_bodies,
                    "optitrack_marker_sets": ({} if self.optitrack_monitor is None else
                                              self.optitrack_monitor.marker_snapshot(now)),
                    "xsens_position": self.xsens_position,
                    "xsens_frame": self.xsens_frame,
                    "stale": self.optitrack_stale or xsens_sample.stale or tcp is None,
                    "xsens_age_s": round(xsens_sample.age_s, 5),
                    "optitrack_source_time_s": None if sample is None else sample.motive_timestamp,
                    "geometry_reference": dict(self.geometry_reference),
                    "age_s": (None if self.optitrack_age_s is None else
                              round(self.optitrack_age_s, 5)),
                    "features": feature,
                    "body_tracking": self.body_tracking,
                    "ground_truth": self.label,
                    "ground_truth_phase": self.label,
                    "ground_truth_event": self.event_label,
                    "event_label_basis": "planned_cue_window_not_observed_onset",
                    "hmm_state": state,
                    "hmm_posterior": posterior,
                    "controller_decision": controller_decision,
                    "controller_comparison": comparison,
                    "study_release_sha256": (self.study_release or {}).get("sha256"),
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
                self.file.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
                self.file.flush()
                self.samples_written += 1
                sample_t = float(record["t"])
                if self._catalog_first_t is None:
                    self._catalog_first_t = sample_t
                self._catalog_last_t = sample_t
                if record["stale"]:
                    self._catalog_stale += 1
                label = str(record["ground_truth_phase"])
                event = str(record["ground_truth_event"])
                self._catalog_label_counts[label] = (
                    self._catalog_label_counts.get(label, 0) + 1
                )
                self._catalog_event_counts[event] = (
                    self._catalog_event_counts.get(event, 0) + 1
                )
                if label != "unlabelled" and label != self._catalog_previous_label:
                    self._catalog_sequence.append(label)
                self._catalog_previous_label = label

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
                      video_recording_reference: object = None,
                      execution_mode: str = "operator_confirmed") -> dict:
        with self.lock:
            if self.recording:
                raise ValueError("A recording is already active")
            if self.pipeline_error is not None:
                raise ValueError("Capture/controller pipeline failed; restart the service before a new trial")
            current_release = release_fingerprint(
                Path(__file__).resolve().parents[1], self.model_sha256, self.config)
            for name, digest in self.runtime_release["files"].items():
                if (name.endswith((".py", ".tsx")) or name == "configs/mocap_extrinsics.yaml") and current_release["files"].get(name) != digest:
                    raise ValueError("Study code changed after this service started; restart it before a new trial")
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
            # External references are optional legacy metadata. Stream capture
            # starts here, with server-generated filenames, for every trial.
            native_reference = str(mvn_recording_reference or "").strip()
            motive_reference = str(motive_recording_reference or "").strip()
            video_reference = str(video_recording_reference or "").strip()
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
                telemetry = (self.rig.telemetry_snapshot(allow_connect=False)
                             if self.rig is not None else {})
                if live_tcp_position(telemetry) is None:
                    raise ValueError("A fresh live robot TCP pose is required for structured separation measurements")
            # Every recorded trial is an independent sequence. Do not let the
            # previous trial's HMM belief or derivative windows leak across it.
            self.hmm.reset()
            self.extractor.reset()
            self.body_tracker.reset()
            self.feature = None
            self.feature_status = "warming_up"
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
            self.shadow_controllers = (ControllerComparison(self.config, self.hmm)
                                       if implementation is not None else None)
            self.controller_comparison = None
            self.event_exposure = EventExposure(self.config)
            self.study_release = current_release
            self.participant_id = safe_id(participant, "P00")
            self.trial_id = safe_id(trial, "T00")
            self.block_label = block or None
            self.within_block_trial = within or None
            self.controller_condition = controller or None
            self.planned_event = event or None
            self.collection_mode = mode
            self.execution_mode = execution_mode
            self.automation_contract = None
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
            self._catalog_first_t = None
            self._catalog_last_t = None
            self._catalog_stale = 0
            self._catalog_label_counts = {}
            self._catalog_event_counts = {}
            self._catalog_sequence = []
            self._catalog_previous_label = None
            self.mvn_recording_confirmed = bool(mvn_recording_confirmed is True and native_reference)
            self.mvn_recording_reference = native_reference[:500] or None
            self.motive_recording_reference = motive_reference[:500] or None
            self.video_recording_reference = video_reference[:500] or None
            self.label = "unlabelled"
            self.event_label = "none"
            self.guided_step = 0
            self.recording = True
            self._journal_event_locked("trial_started", capture_mode=self.capture_mode,
                                       clock_basis="local_monotonic", external_sync_verified=False)
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
            duration_s = max(
                0.0,
                (self._catalog_last_t - self._catalog_first_t)
                if self._catalog_first_t is not None and self._catalog_last_t is not None
                else 0.0,
            )
            rate_hz = self.samples_written / duration_s if duration_s > 0 else 0.0
            stale_ratio = (
                self._catalog_stale / self.samples_written
                if self.samples_written else 1.0
            )
            automatic = self.execution_mode == "automatic"
            quality = RunCatalog._quality(
                self.samples_written, duration_s, rate_hz, stale_ratio,
                self._catalog_label_counts, self._catalog_sequence, 0,
                self._catalog_event_counts, self.planned_event,
                automatic=automatic, completed=outcome == "completed",
            )
            exposure = self.event_exposure.status(self.planned_event)
            if exposure["review_reason"] and quality["grade"] == "good":
                quality = {**quality, "grade": "review", "label": "REVIEW EVENT",
                           "reasons": quality["reasons"] + [exposure["review_reason"]]}
            label_seconds = {
                label: round(count / rate_hz, 1) if rate_hz > 0 else 0.0
                for label, count in self._catalog_label_counts.items()
            }
            catalog_summary = {
                "session_id": self.session_id,
                "participant_id": self.participant_id,
                "trial_id": self.trial_id,
                "block_label": self.block_label,
                "within_block_trial": self.within_block_trial,
                "controller_condition": self.controller_condition,
                "planned_event": self.planned_event,
                "collection_mode": self.collection_mode,
                "started_at": RunCatalog._started_at(self.session_id or "", time.time()),
                "execution_mode": self.execution_mode,
                "file_name": Path(self.recording_path or "").name,
                "completed": outcome == "completed",
                "samples": self.samples_written,
                "duration_s": round(duration_s, 1),
                "rate_hz": round(rate_hz, 1),
                "stale_percent": round(stale_ratio * 100, 2),
                "labels": label_seconds,
                "events": dict(self._catalog_event_counts),
                "sequence": list(self._catalog_sequence),
                "quality": quality,
            }
            manifest = {
                "schema_version": 1,
                "capture_mode": self.capture_mode,
                "capture_contents": {
                    "sampled_streams": ["xsens_segments", "optitrack_tracking", "robot_telemetry"],
                    "derived": ["features", "helmet_anchored_body", "body_features", "controller_decisions", "task_events"],
                    "native_files_created": False, "video_recorded": False,
                    "external_sync_verified": False,
                },
                "session_id": self.session_id,
                "participant_id": self.participant_id,
                "trial_id": self.trial_id,
                "collection_mode": self.collection_mode,
                "block_label": self.block_label,
                "within_block_trial": self.within_block_trial,
                "controller_condition": self.controller_condition,
                "planned_event": self.planned_event,
                "outcome": outcome,
                "execution_mode": self.execution_mode,
                "automation_contract": self.automation_contract,
                "study_release": self.study_release,
                "event_exposure": exposure,
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
                "catalog_summary": catalog_summary,
            }
            temporary_manifest = manifest_path.with_suffix('.json.tmp')
            temporary_manifest.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            temporary_manifest.replace(manifest_path)
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
            "execution_mode": self.execution_mode,
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
        """Open the planned cue window; telemetry separately verifies motion."""
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
            if self.capture_mode != "automatic_streams" and self.guided_step == 0 and self.sync_marker_count < 1:
                raise ValueError(
                    "Record the shared sync marker before starting the approach"
                )
            if self.guided_step >= len(GUIDED_PROTOCOL_LABELS) - 1:
                raise ValueError("Guided sequence is complete; stop and save the run")
            self.guided_step += 1
            self.label, self.event_label = GUIDED_PROTOCOL_LABELS[self.guided_step]
            if self.execution_mode == "automatic":
                # Keep this inside the same state lock as the step update;
                # otherwise the sampling thread can log a machine transition
                # as a human ground-truth frame before the caller resets it.
                self.label = "unlabelled"
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
                "service": dict(self.service),
                "connected": self.connected,
                "packets": self.packets,
                "packet_rate_hz": round(rate, 1),
                "stale": age is None or age > 0.150,
                "age_s": None if age is None else round(age, 4),
                "position": self.position,
                "xsens_position": self.xsens_position,
                "hand_tracking": {
                    "anchored_body": self.body_tracking,
                    "xsens_sample_counter": (None if self.xsens_frame is None else self.xsens_frame.get("sample_counter")),
                    "xsens_age_s": (None if self.xsens_frame_wall is None else now - self.xsens_frame_wall),
                    "xsens_hands": ({} if self.xsens_frame is None else {
                        k: self.xsens_frame["segments"].get(k) for k in ("11", "15")}),
                    "optitrack_markers": ({} if self.optitrack_monitor is None else
                                          self.optitrack_monitor.marker_snapshot(now)),
                    "panel": (None if self.optitrack_monitor is None else
                              next((asdict(p) for i, p in self.optitrack_monitor.snapshot(now).items() if i == 2), None)),
                },
                "xsens_segment_count": (0 if self.xsens_frame is None else
                                         len(self.xsens_frame["segments"])),
                "optitrack_connected": not self.optitrack_stale,
                "optitrack_age_s": (None if self.optitrack_age_s is None else
                                    round(self.optitrack_age_s, 4)),
                "feature": self.feature,
                "body_tracking": self.body_tracking,
                "feature_status": self.feature_status,
                "posterior": self.posterior,
                "hmm_state": self.hmm_state,
                "model_source": self.model_source,
                "model_sha256": self.model_sha256,
                "model_health": self.model_health,
                "recognition_feature_order": list(self.hmm.feature_order),
                "recognition_uses_xsens": any(name.startswith("body.") for name in self.hmm.feature_order),
                "pipeline_error": self.pipeline_error,
                "geometry_reference": dict(self.geometry_reference),
                "event_exposure": self.event_exposure.status(self.planned_event),
                "controller_comparison": self.controller_comparison,
                "controller_profile": {
                    "mode": "ssm",
                    "red_radius_m": (self.config["zones"]["K"] * self.config["zones"]["T"]
                                     + self.config["zones"]["C"] + self.config["zones"]["Sa"]),
                    "predictive_role": "Earlier caution for rapid closing; all controllers share the red stop boundary.",
                },
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
                "capture_mode": self.capture_mode,
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
            source_clock = getattr(recv, "getTimestamp", None)
            if source_clock is not None:
                source_time = float(source_clock())
                if not math.isfinite(source_time):
                    raise ValueError("Invalid RTDE source timestamp")
                last_source = getattr(self, "_last_telemetry_source", None)
                if last_source is None or last_source[0] != source_time:
                    self._last_telemetry_source = (source_time, time.monotonic())
                result["source_timestamp_s"] = source_time
                result["source_age_s"] = time.monotonic() - self._last_telemetry_source[1]
            for key, name in getters.items():
                fn = getattr(recv, name, None)
                if fn is None:
                    continue
                value = fn()
                if isinstance(value, (list, tuple)):
                    if not all(math.isfinite(float(v)) for v in value):
                        raise ValueError(f"Invalid RTDE {key}")
                    result[key] = [round(float(v), 6) for v in value]
                elif value is not None:
                    if isinstance(value, float) and not math.isfinite(value):
                        raise ValueError(f"Invalid RTDE {key}")
                    result[key] = float(value) if isinstance(value, float) else value
        except Exception as exc:
            self._recv = None
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        return result

    def fresh_telemetry_snapshot(self) -> dict:
        """Read one independent RTDE sample after a cached receiver goes stale.

        The long-lived receiver can retain its final sample after a robot
        restart.  Trial preflight must not confuse that stale cache with a
        moving arm, so an explicit start may verify the current joint velocity
        through a short-lived connection instead.
        """
        recv = None
        try:
            with socket.create_connection((self.robot_host, 30004), timeout=0.25):
                pass
            from rtde_receive import RTDEReceiveInterface
            recv = RTDEReceiveInterface(self.robot_host)
            source_time = float(recv.getTimestamp())
            qd = [float(value) for value in recv.getActualQd()]
            if (not math.isfinite(source_time) or len(qd) != 6
                    or not all(math.isfinite(value) for value in qd)):
                raise ValueError("Invalid fresh RTDE stationary sample")
            return {
                "available": True,
                "sampled_monotonic_s": round(time.monotonic(), 6),
                "source_timestamp_s": source_time,
                "source_age_s": 0.0,
                "actual_qd": [round(value, 6) for value in qd],
            }
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if recv is not None:
                try:
                    recv.disconnect()
                except Exception:
                    pass

    def apply_research_speed_fraction(self, speed_fraction: float) -> dict:
        """Write the UR speed slider for the research controller.

        This output is useful for experimental integration but is not a
        safety-rated stop channel. Port reachability is checked before importing
        the native RTDE client so an offline robot cannot freeze the ticker.
        """
        fraction = max(0.0, min(1.0, float(speed_fraction)))
        with self._output_lock:
            if (self._last_speed_fraction is not None and
                    abs(self._last_speed_fraction - fraction) < 1e-6 and
                    time.monotonic() - getattr(self, "_last_speed_write_at", 0.0) < 0.1):
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
                self._last_speed_fraction = None
                return {
                    "applied": False, "changed": False,
                    "status": "write_failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "speed_fraction": fraction,
                }
            if applied:
                self._last_speed_fraction = fraction
                self._last_speed_write_at = time.monotonic()
                self._last_output_failure = None
            else:
                self._last_speed_fraction = None
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
                else:
                    # A failed refresh must not masquerade as a fresh seal.
                    return {"error": out.get("error", "gripper refresh failed")}
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

    def goto_pose(self, name: str, speed: float = 0.10, *, guard=None,
                  cancel: threading.Event | None = None) -> dict:
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
            target = [float(v) for v in pose["q"]]
            if len(target) != 6 or not all(math.isfinite(v) for v in target):
                raise ValueError("Invalid taught joint pose")
            if guard is not None:
                # Robot-side watchdog stops this script if the host loop stalls.
                # Neither this nor stopJ is an independent safety-rated chain.
                guard()
                if cancel is not None and cancel.is_set():
                    raise ValueError("Automatic motion cancelled")
                if control.setWatchdog(2.0) is False:
                    raise ValueError("Could not enable motion watchdog")
                moved = control.moveJ(target, spd, 0.15, True)
            else:
                moved = control.moveJ(target, spd, 0.15)
            if not moved:
                raise ValueError(f"move to {name} failed")
            if guard is not None:
                deadline = time.monotonic() + 90.0
                while True:
                    if cancel is not None and cancel.is_set():
                        raise ValueError("Automatic motion cancelled")
                    guard()
                    if control.kickWatchdog() is False:
                        raise ValueError("Motion watchdog communication failed")
                    if control.getAsyncOperationProgress() < 0:
                        actual = self.pose_status()
                        q = actual.get("q") or []
                        if (not actual.get("available") or len(q) != 6
                                or not all(math.isfinite(float(v)) for v in q)
                                or max(abs(float(a) - b) for a, b in zip(q, target)) > 0.08):
                            raise ValueError("Motion ended without reaching the taught pose")
                        break
                    if time.monotonic() >= deadline:
                        raise ValueError("Automatic motion timed out")
                    time.sleep(0.05)
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
    """Coordinate operator motion requests and the guided trial labels.

    One press requests each physical action.  Lift/lower requests are accepted
    even while the participant is inside a controller zone: the selected study
    controller owns the live speed slider and may hold, slow, or resume the
    already-requested move.  Tracking/output loss still cancels the RTDE move.
    The panel is released only after a stationary dwell at the taught low pose.
    """

    GRIP_MIN_PERMILLE = 500
    RELEASED_MAX_PERMILLE = 100
    POSE_TOLERANCE_RAD = 0.08
    ARM_MIN_DELAY_S = 0.75
    ARM_TIMEOUT_S = 5.0
    LOW_RELEASE_DWELL_S = 1.5

    def __init__(self, state: DashboardState, rig: RigControl,
                 clock=time.monotonic, sleeper=time.sleep) -> None:
        self.state = state
        self.rig = rig
        self.clock = clock
        self.sleeper = sleeper
        self.lock = threading.Lock()
        self.cancel = threading.Event()
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
        if not math.isfinite(distance) or distance < self.motion_clearance_m:
            raise ValueError(
                f"Operator is {distance:.2f} m from the robot; move beyond "
                f"{self.motion_clearance_m:.2f} m before confirming cell clear"
            )
        return distance

    def _require_motion_controller(self) -> tuple[dict, float]:
        """Require a fresh controller output without pre-vetoing its zone.

        A zero speed fraction is a valid controller decision: it means the
        requested move remains held until later samples permit motion.
        """
        snap = self.state.snapshot()
        if (not snap.get("recording") or not snap.get("connected")
                or snap.get("stale") or not snap.get("optitrack_connected")
                or snap.get("xsens_segment_count", 0) < MVN_FULL_BODY_SEGMENTS):
            raise ValueError("Fresh Xsens and OptiTrack data are required for robot motion")
        distance = (snap.get("feature") or {}).get("d")
        if distance is None or not math.isfinite(float(distance)):
            raise ValueError("Valid operator separation is required for robot motion")
        if not snap.get("controller_output_enabled"):
            raise ValueError("The experiment controller output is switched off")
        decision = snap.get("controller_decision") or {}
        updated = float(getattr(self.state, "controller_updated_at", 0.0))
        fraction = decision.get("speed_fraction")
        if (self.clock() - updated > 0.5 or not decision.get("output_applied")
                or fraction is None or not math.isfinite(float(fraction))):
            raise ValueError("The experiment controller output is stale or unavailable")
        return snap, float(distance)

    def _manual_motion_guard(self) -> None:
        if self.cancel.is_set():
            raise ValueError("Operator stopped the requested motion")
        snap = self.state.snapshot()
        def hold_at_zero(reason: str) -> None:
            held = self.rig.apply_research_speed_fraction(0.0)
            if not held.get("applied"):
                raise ValueError(
                    f"{reason} and the zero-speed hold could not be applied: "
                    + str(held.get("error") or held.get("status") or "unknown output error")
                )

        tracking_invalid = (
            not snap.get("connected")
            or snap.get("stale")
            or not snap.get("optitrack_connected")
            or snap.get("xsens_segment_count", 0) < MVN_FULL_BODY_SEGMENTS
            or (snap.get("feature") or {}).get("d") is None
        )
        if tracking_invalid:
            # A short sensor gap is a zero-speed HOLD, not cancellation of the
            # operator's lift/lower request.  Apply the hold synchronously so
            # the async RTDE move remains alive; the 60 Hz controller ticker
            # restores its permitted fraction when fresh tracking returns.
            if not snap.get("recording"):
                raise ValueError("The guided recording ended during robot motion")
            if not snap.get("controller_output_enabled"):
                raise ValueError("The experiment controller output is switched off")
            hold_at_zero("Tracking was interrupted")
            return
        try:
            self._require_motion_controller()
        except ValueError as exc:
            # Constructing RTDEControlInterface briefly holds the Python GIL on
            # this Windows host.  The sensor ticker cannot refresh its decision
            # during that native connect, so the first post-connect guard can
            # be stale even though the preflight was fresh.  Preserve the
            # request at zero; the ticker immediately restores the selected
            # controller fraction once it runs again.
            if "controller output is stale or unavailable" not in str(exc):
                raise
            hold_at_zero("The controller refresh was briefly delayed")

    def _require_pose(self, name: str) -> dict:
        target = self.rig._poses.get(name, {}).get("q")
        pose = self.rig.pose_status()
        current = pose.get("q")
        if (not target or len(target) != 6 or not pose.get("available")
                or not current or len(current) != 6
                or not all(math.isfinite(float(v)) for v in [*target, *current])):
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
              video_recording_reference: object = None,
              vacuum: int = 60) -> dict:
        """Preflight the low, released rig before opening a guided recording."""
        with self.lock:
            self._clear_arm()
            self.cancel.clear()
            self._require_robot_ready()
            self._require_operator_clear()
            self._require_pose("pose1_low")
            stats = self.rig.gripper_stats(max_age_s=0.0)
            if stats.get("error") or not all(k in stats for k in ("vacuum_A_permille", "vacuum_B_permille", "pump_rpm")):
                raise ValueError("Cannot verify released gripper; fresh telemetry is required")
            released_vacuum = (int(stats.get("vacuum_A_permille", 0)),
                               int(stats.get("vacuum_B_permille", 0)))
            pump = int(stats.get("pump_rpm", 0))
            if max(released_vacuum) > self.RELEASED_MAX_PERMILLE or pump > 100:
                raise ValueError(
                    "Guided run requires the arm low with suction off; "
                    "use the manual recovery controls to release the current panel first"
                )
            metadata = (block_label, within_block_trial,
                        controller_condition, planned_event)
            extra = ({"execution_mode": "automatic"}
                     if getattr(self, "automatic_requested", False) else {})
            if any(value is not None for value in metadata) or collection_mode in {"qualification", "participant_study"}:
                result = self.state.start_session(
                    participant, trial, mvn_recording_confirmed,
                    mvn_recording_reference, block_label, within_block_trial,
                    controller_condition, planned_event, collection_mode,
                    motive_recording_reference, video_recording_reference, **extra)
            else:
                result = self.state.start_session(
                    participant, trial, mvn_recording_confirmed,
                    mvn_recording_reference, **extra)
            suction = None
            if not getattr(self, "automatic_requested", False):
                self._journal("manual_loading_suction_requested", vacuum_percent=int(vacuum))
                suction = self.rig.gripper_action("grip", "BOTH", int(vacuum))
                if not suction.get("ok"):
                    self.state.stop_session(outcome="aborted")
                    raise ValueError(
                        "Could not start loading suction: "
                        + str(suction.get("error", "unknown gripper error"))
                    )
                self._journal("manual_loading_suction_enabled", vacuum_percent=int(vacuum))
            return {**result, "preflight": {
                "pose": "pose1_low", "vacuum": released_vacuum,
                "operator_clearance_m": self.motion_clearance_m,
                "loading_suction": "on" if suction is not None else "automatic",
            }}

    def complete_step(self, vacuum: int = 60) -> dict:
        """Complete the visible instruction, perform its action, then advance."""
        with self.lock:
            snap = self.state.snapshot()
            if not snap.get("recording") or snap.get("guided_step") is None:
                raise ValueError("No guided recording is active")
            step = int(snap["guided_step"])
            self._clear_arm()
            if (snap.get("capture_mode") != "automatic_streams"
                    and step == 0 and int(snap.get("sync_marker_count", 0)) < 1):
                raise ValueError(
                    "Record the shared sync marker before starting the approach"
                )
            action: dict | None = None
            self._journal("guided_action_requested", guided_step=step)

            if step == 2:  # panel aligned at the low gripper
                stats = self.rig.gripper_stats(max_age_s=0.0)
                seal = (int(stats.get("vacuum_A_permille", 0)),
                        int(stats.get("vacuum_B_permille", 0)))
                if stats.get("error") or min(seal) < self.GRIP_MIN_PERMILLE:
                    raise ValueError(
                        f"Panel grip is not sealed yet: vacuum {seal}. "
                        "Suction remains on; reseat the panel and press again."
                    )
                action = {"verified": True, "stats": stats}
            elif step == 3:  # participant has retreated; lift the panel
                _, distance = self._require_motion_controller()
                self._require_robot_ready()
                # Robot travel is not a human-motion training state. Exclude
                # the blocking motion interval rather than recording a long
                # stationary segment as "retreating".
                self.state.set_label("unlabelled")
                self.state.begin_planned_event_window(source="robot_lift")
                try:
                    action = self.rig.goto_pose(
                        "pose2_top", guard=self._manual_motion_guard,
                        cancel=self.cancel)
                except Exception:
                    self.state.end_planned_event_window(source="robot_lift")
                    self.state.set_label("retreating")
                    raise
                self.state.end_planned_event_window(source="robot_lift")
                action["operator_distance_m"] = round(distance, 3)
            elif step == 8:  # participant has retreated after the overhead task
                _, distance = self._require_motion_controller()
                self._require_robot_ready()
                self.state.set_label("unlabelled")
                try:
                    action = self.rig.goto_pose(
                        "pose1_low", guard=self._manual_motion_guard,
                        cancel=self.cancel)
                except Exception:
                    self.state.set_label("retreating")
                    raise
                action["operator_distance_m"] = round(distance, 3)
                self._require_pose("pose1_low")
                self.sleeper(self.LOW_RELEASE_DWELL_S)
                if self.cancel.is_set():
                    raise ValueError("Operator stopped before low-pose release")
                self._require_robot_ready()
                self._require_pose("pose1_low")
                release = self.rig.gripper_action("release", "BOTH", 0)
                if not release.get("ok"):
                    raise ValueError(
                        f"Panel release failed: {release.get('error', 'unknown error')}"
                    )
                self._journal(
                    "guided_action_completed", guided_step=step,
                    action_summary=str({"motion": action, "release": release})[:500])
                saved = self.state.stop_session(outcome="completed")
                return {
                    **saved, "completed": True,
                    "action": {"motion": action, "release": release},
                }
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
            if step == 3 and advanced.get("guided_step") == 4:
                # Once the lift reaches the top, the participant may begin the
                # second approach immediately; no empty acknowledgement screen.
                advanced = self.state.advance_guided_protocol()
            if action is not None:
                self._journal(
                    "guided_action_completed", guided_step=step,
                    action_summary=str(action)[:500])
            return {**advanced, "action": action}


class AutomaticRunController(GuidedRunController):
    """Single-cycle automation for the *current*, suction-held panel task.

    Unlike the legacy ceiling-fastening demo this never releases overhead.
    Rehearsals and participant studies use the same guarded sequence. Collection
    mode identifies the dataset; no model belief chooses a task transition or
    becomes ground-truth labels.
    """

    VERSION = "automatic-panel-v7-helmet-body-task"
    COLLECTION_PREFIXES = {"qualification": "Q", "participant_study": "P"}
    SEAL_DWELL_S = 1.0
    LOW_RELEASE_DWELL_S = 2.0
    CLEAR_DWELL_S = 2.0
    HEALTH_MAX_AGE_S = 2.0
    WAIT_TIMEOUT_S = 120.0

    def __init__(self, state, rig, clock=time.monotonic, *, enabled=False):
        super().__init__(state, rig, clock)
        self.enabled = enabled
        self.automatic = False
        self.cancel = threading.Event()
        self.phase = "idle"
        self.reason = ("Automatic trials available; hardware preflight required" if enabled
                       else "Automatic trials are disabled on this server")
        self.since = self.clock()
        self.stable_since = None
        self.health = None
        self.health_lock = threading.Lock()
        self.lock = threading.RLock()
        self.contract = None
        task = state.config.get('drilling_task', {})
        self.drilling = SimulatedDrilling(radius_m=task.get('radius_m', .12),
                                         dwell_s=task.get('dwell_s', 1.0),
                                         max_gap_s=task.get('max_gap_s', .15))
        visit_config = state.config.get("work_location_observation")
        self.work_visits = None
        if visit_config:
            if visit_config.get("frame") != "robot_base" or visit_config.get("units") != "m":
                raise ValueError("Work locations must be measured head positions in robot_base metres")
            self.work_visits = WorkLocationVisits(
                visit_config["head_positions"], radius_m=visit_config.get("radius_m", 0.25),
                dwell_s=visit_config.get("dwell_s", 2.0),
                max_gap_s=visit_config.get("max_gap_s", 0.25))

    def _build_contract(self, vacuum):
        poses = {}
        for name in ("pose1_low", "pose2_top"):
            q = [float(v) for v in self.rig._poses.get(name, {}).get("q", [])]
            if len(q) != 6 or not all(math.isfinite(v) for v in q):
                raise ValueError(f"A valid taught {name} pose is required")
            poses[name] = q
        body = {"version": self.VERSION, "poses_q_rad": poses,
                "helmet_body": self.state.config.get('helmet_body'),
                "drilling_task": self.state.config.get('drilling_task'),
                "vacuum_percent": int(vacuum), "joint_speed_rad_s": 0.10,
                "grip_min_permille": self.GRIP_MIN_PERMILLE,
                "seal_dwell_s": self.SEAL_DWELL_S,
                "clearance_m": self.motion_clearance_m,
                "clear_dwell_s": self.CLEAR_DWELL_S,
                "low_release_dwell_s": self.LOW_RELEASE_DWELL_S,
                "low_release_support": "panel rests on rigid gripper support at pose1_low",
                "health_max_age_s": self.HEALTH_MAX_AGE_S,
                "wait_timeout_s": self.WAIT_TIMEOUT_S,
                "sequence": ["loading", "retreat_lift", "lifting", "task",
                             "retreat_lower", "lowering", "supported_release"]}
        signature = hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return {**body, "sha256": signature}

    def _require_unchanged_contract(self):
        if self.contract is None or self._build_contract(self.contract["vacuum_percent"]) != self.contract:
            raise ValueError("Task poses/settings changed during trial; abort and requalify")

    def presentation(self):
        """One server-owned instruction; no guessed sensor or motion state."""
        phase = self.phase
        cues = {
            "ready": (1, "Get ready", None),
            "loading": (1, "Place the panel against both cups", None),
            "retreat_lift": (2, "Let go and step back", None),
            "lifting": (3, "Lift requested — stay clear", None),
            "task": (4, "Complete one lap and the simulated drilling gestures", "Lap complete — begin retreat"),
            "retreat_lower": (5, "Step back for lowering", None),
            "lowering": (6, "Lowering requested — stay clear", None),
            "supported_release": (7, "Panel at low support — releasing after two seconds", None),
            "releasing": (7, "Releasing suction and saving", None),
            "fault": (None, "Trial stopped — do not restart", None),
            "complete": (7, "Trial saved", None),
        }
        number, title, action = cues.get(phase, (None, "Automatic trial", None))
        if phase == 'task' and self._automatic_body_task():
            title = f"Drilling gestures: {self.drilling.status()['completed_count']}/4 corners complete"
            action = None
        cue_instruction = None
        if phase == "lifting":
            snap = self.state.snapshot()
            if snap.get("event_exposure", {}).get("robot_moving"):
                event = snap.get("planned_event")
                title = {"rapid intrusion": "Motion underway: give the approved rapid-intrusion cue",
                         "distractor": "Motion underway: give the approved distractor cue"}.get(
                             event, "Motion underway: clean trial, no event cue")
                cue_instruction = "Use only the pre-briefed movement and route. The event window ends when lifting finishes."
        sync_required = (self.automatic and phase == "loading"
                         and self.state.snapshot().get("capture_mode") != "automatic_streams"
                         and self.state.snapshot().get("sync_marker_count", 0) < 1)
        if sync_required:
            title = "Suction on — record shared sync"
        return {"stage": number, "stages_total": 7, "title": title,
                "instruction": cue_instruction or self.reason, "action_label": action,
                "sync_required": sync_required,
                "automatic_wait": self.automatic and action is None}

    def status(self):
        return {"enabled": self.enabled, "active": self.automatic,
                "availability": "automatic_ready" if self.enabled else "service_disabled",
                "supported_collection_modes": list(self.COLLECTION_PREFIXES),
                "work_locations": ({"configured": False} if self.work_visits is None else
                                   {"configured": True, **self.work_visits.status()}),
                "simulated_drilling": self.drilling.status(),
                "qualification_only": False, "version": self.VERSION,
                "phase": self.phase, "reason": self.reason,
                "fault": self.phase == "fault", "presentation": self.presentation(),
                "task_sha256": None if self.contract is None else self.contract["sha256"]}

    def _phase(self, phase, reason):
        if self.cancel.is_set() and phase != "fault":
            return
        self.phase, self.reason = phase, reason
        self.since, self.stable_since = self.clock(), None
        self._journal("automation_transition", phase=phase, reason=reason,
                      protocol_version=self.VERSION)

    def start(self, *args, automatic=False, vacuum=60, **kwargs):
        with self.lock:
            return self._start(*args, automatic=automatic, vacuum=vacuum, **kwargs)

    def _start(self, *args, automatic=False, vacuum=60, **kwargs):
        if self.state.snapshot().get("recording"):
            raise ValueError("A recording is already active")
        if automatic:
            if not self.enabled:
                raise ValueError("Automatic trials require --enable-automatic-trials; restart the service with Start-Lab.ps1")
            mode = kwargs.get("collection_mode")
            prefix = self.COLLECTION_PREFIXES.get(mode)
            if prefix is None:
                raise ValueError("Automatic trials require participant study or qualification mode; model development is labelled separately")
            participant = str(args[0] if args else "")
            if not re.fullmatch(rf"{prefix}\d+", participant):
                raise ValueError(f"{mode} requires a {prefix}-code so participant and rehearsal data stay separate")
            if not 10 <= int(vacuum) <= 80:
                raise ValueError("Loading vacuum must be between 10 and 80 percent")
            self._require_stationary()
            contract = self._build_contract(vacuum)
        self.automatic = False
        self.automatic_requested = automatic
        self.cancel.clear()
        result = super().start(*args, vacuum=vacuum, **kwargs)
        self.automatic = automatic
        self.contract = contract if automatic else None
        self.drilling.reset()
        if self.work_visits is not None:
            self.work_visits.reset()
        self.state.automation_contract = self.contract
        self.health = None
        self._phase("ready", "Operator-confirmed run")
        if automatic:
            # Start trial is the explicit actuation command. No later suction
            # click, inferred-state trigger or service-start side effect.
            try:
                self._journal("automation_task_contract", **self.contract)
                self._require_unchanged_contract()
                self._require_stationary()
                self._journal("automation_loading_suction_requested", vacuum_percent=int(vacuum))
                if self.cancel.is_set():
                    raise ValueError("Trial stopped before loading suction")
                action = self.rig.gripper_action("grip", "BOTH", int(vacuum))
                if not action.get("ok"):
                    raise ValueError("Loading suction command failed; inspect rig")
                if self.cancel.is_set():
                    raise ValueError("Trial stopped during loading suction")
                self.refresh_health()
                self._health(require_grip=False)
                self._journal("automation_loading_suction_enabled", vacuum_percent=int(vacuum))
                self._phase("loading", "Data capture started. Suction on; place the panel against both cups")
            except Exception as exc:
                self.request_stop(str(exc))
                # Preserve this failed attempt and never vent automatically.
                raise ValueError(f"Trial faulted during suction startup: {exc}") from exc
        return {**result, "automation": self.status()}

    def _require_stationary(self):
        telemetry = self.rig.telemetry_snapshot()
        qd = telemetry.get("actual_qd") or []
        structurally_fresh = (
            telemetry.get("available")
            and len(qd) == 6
            and 0 <= float(telemetry.get("source_age_s", math.inf)) <= 0.25
            and all(math.isfinite(float(v)) for v in qd)
        )
        if not structurally_fresh:
            refresh = getattr(self.rig, "fresh_telemetry_snapshot", None)
            if callable(refresh):
                telemetry = refresh()
        qd = telemetry.get("actual_qd") or []
        if (not telemetry.get("available") or len(qd) != 6
                or not 0 <= float(telemetry.get("source_age_s", math.inf)) <= 0.25
                or not all(math.isfinite(float(v)) for v in qd)
                or max(abs(float(v)) for v in qd) > 0.005):
            raise ValueError("Cannot verify the robot is stationary")

    def refresh_health(self):
        if not self.automatic or self.cancel.is_set():
            return
        # Stamp BEFORE slow IO. A 30-second stalled SSH call is not fresh data
        # just because it eventually returned. Motion never waits on this IO.
        started = self.clock()
        try:
            health = {"at": started,
                      "grip": self.rig.gripper_stats(max_age_s=0.0),
                      "robot": self.rig.robot_status()}
        except Exception as exc:
            health = {"at": started, "error": str(exc)}
        with self.health_lock:
            if self.health is None or health["at"] >= self.health["at"]:
                self.health = health

    def _tracking(self):
        snap = self.state.snapshot()
        if (not snap.get("recording") or not snap.get("connected")
                or snap.get("stale") or not snap.get("optitrack_connected")
                or snap.get("xsens_segment_count", 0) < MVN_FULL_BODY_SEGMENTS):
            raise ValueError("Recording or tracking unavailable")
        distance = (snap.get("feature") or {}).get("d")
        if distance is None or not math.isfinite(float(distance)):
            raise ValueError("Valid separation unavailable")
        return snap, float(distance)

    def _health(self, require_grip=True):
        with self.health_lock:
            health = self.health
        if not health or not 0 <= self.clock() - health["at"] <= self.HEALTH_MAX_AGE_S:
            raise ValueError("Robot/gripper telemetry stale")
        robot = health.get("robot", {})
        if (health.get("error") or not robot.get("reachable")
                or robot.get("robotmode") != "Robotmode: RUNNING"
                or robot.get("safety") != "Safetystatus: NORMAL"):
            raise ValueError("Robot health is not normal")
        grip = health.get("grip", {})
        if grip.get("error"):
            raise ValueError("Gripper read failed")
        seal = [float(grip.get(k, -1)) for k in ("vacuum_A_permille", "vacuum_B_permille")]
        if not all(math.isfinite(v) and v >= 0 for v in seal):
            raise ValueError("Invalid gripper pressure")
        sealed = min(seal) >= self.GRIP_MIN_PERMILLE
        if require_grip and not sealed:
            raise ValueError("Vacuum grip lost; suction remains on")
        return sealed

    def _motion_guard(self):
        if self.cancel.is_set():
            raise ValueError("Automatic trial stopped")
        self._require_unchanged_contract()
        snap, _ = self._tracking()
        if self.state.config.get('helmet_body', {}).get('enabled') and not (snap.get('body_tracking') or {}).get('available'):
            raise ValueError("Fresh helmet-anchored body tracking is required during motion")
        self._health()
        # Distance does NOT veto the assigned event here: the selected safety
        # controller must govern the same trajectory in all three conditions.
        # Tracking/output failure is an independent, latched fault instead.
        decision = snap.get("controller_decision") or {}
        updated = getattr(self.state, "controller_updated_at", 0.0)
        if (self.clock() - updated > 0.5 or not decision.get("output_applied")):
            raise ValueError("Research controller output is stale or failed")

    def _stable(self, condition, duration):
        if not condition:
            self.stable_since = None
            return False
        if self.stable_since is None:
            self.stable_since = self.clock()
        return (self.clock() - self.stable_since >= duration
                and self.health is not None and self.health["at"] > self.stable_since)

    def _advance_to(self, step):
        if self.cancel.is_set():
            raise ValueError("Automatic trial stopped")
        while int(self.state.snapshot()["guided_step"]) < step:
            self.state.advance_guided_protocol()
        # Machine-detected boundaries are not independent human annotations.
        self.state.set_label("unlabelled")

    def arm_step(self):
        if not self.automatic:
            return super().arm_step()
        raise ValueError("Automatic steps do not need arming; low-support release uses a stationary dwell")

    def complete_step(self, vacuum=60):
        if not self.automatic:
            return super().complete_step(vacuum)
        # Reject duplicate/stale clicks; the background worker owns auto steps.
        if self.cancel.is_set():
            raise ValueError("Trial is faulted; abort and inspect before a new run")
        self._require_unchanged_contract()
        step = self.state.snapshot().get("guided_step")
        with self.lock:
            if step == 7 and self.phase == "task":
                if self._automatic_body_task():
                    raise ValueError("All four tracked drilling gestures must complete; watch the corner progress")
                self._advance_to(8)
                self._phase("retreat_lower", "Lap confirmed complete. Step back; lowering starts automatically after clear dwell")
            else:
                raise ValueError("This step advances automatically; do not confirm it manually")
        return {"message": self.reason, "automation": self.status()}

    def request_stop(self, reason="Operator stop"):
        # Never wait for the controller lock: an in-flight move owns it.
        self.cancel.set()
        self._clear_arm()
        if self.automatic:
            self._phase("fault", reason + "; no automatic restart or suction release")

    def tick(self):
        if not self.automatic or self.cancel.is_set() or self.phase in ("ready", "complete"):
            return
        if not self.lock.acquire(blocking=False):
            return
        try:
            self._require_unchanged_contract()
            initial = self.state.snapshot()
            if (self.phase == "loading" and initial.get("feature_status") == "warming_up"
                    and initial.get("connected") and not initial.get("stale")
                    and initial.get("optitrack_connected") and self.clock() - self.since <= .15):
                # start_session resets derivatives. Wait for its first two fresh
                # samples before testing separation; no movement or phase advance.
                self._health(require_grip=False)
                self.stable_since = None
                self.reason = "Waiting for fresh separation samples; motion remains held"
                return
            snap, distance = self._tracking()
            sealed = self._health(require_grip=self.phase != "loading")
            if self.phase == "loading":
                synced = snap.get("capture_mode") == "automatic_streams" or snap.get("sync_marker_count", 0) >= 1
                self.reason = ("Place panel against both cups; suction is on and seal detection is automatic" if synced
                               else "Suction on. Record shared sync before approaching; motion remains blocked")
                if synced and snap.get("guided_step") == 0:
                    self._advance_to(1)
                if self._stable(synced and sealed, self.SEAL_DWELL_S):
                    self._advance_to(3)
                    self._phase("retreat_lift", "Grip verified. Release panel and step back; lift starts automatically after clear dwell")
            elif self.phase in ("retreat_lift", "retreat_lower"):
                body_clear = True
                if self.state.config.get('helmet_body', {}).get('enabled'):
                    body = snap.get('body_tracking') or {}
                    body_distance = body.get('minimum_segment_distance_m')
                    body_clear = (body.get('available') is True and isinstance(body_distance, (int, float))
                                  and math.isfinite(body_distance) and body_distance >= self.motion_clearance_m)
                    if not body_clear:
                        self.reason = "Step back with both arms and body clear; waiting for fresh helmet-anchored tracking"
                if self._stable(distance >= self.motion_clearance_m and body_clear, self.CLEAR_DWELL_S):
                    lifting = self.phase == "retreat_lift"
                    self._motion_guard()
                    self._phase("lifting" if lifting else "lowering",
                                "Lift command pending/running. Stay clear; the experimenter gives only the pre-briefed event cue after observing motion."
                                if lifting else "Lower command pending/running. Stay at the start marker until the next instruction.")
                    if lifting:
                        self.state.begin_planned_event_window(source="automatic_lift")
                    try:
                        self.rig.goto_pose("pose2_top" if lifting else "pose1_low",
                                           speed=self.contract["joint_speed_rad_s"],
                                           guard=self._motion_guard, cancel=self.cancel)
                    finally:
                        if lifting and self.state.snapshot().get("recording"):
                            self.state.end_planned_event_window(source="automatic_lift")
                    self._advance_to(7 if lifting else 9)
                    self._require_stationary()
                    self._phase("task" if lifting else "supported_release",
                                ("Robot up. Hold either hand near each of the four panel corners; progress is detected automatically"
                                 if self._automatic_body_task() else "Robot up. Complete one lap, then confirm task complete")
                                if lifting else "Panel resting on the low gripper support. Waiting two stationary seconds before suction releases")
            elif self.phase == "task":
                self._observe_simulated_drilling(snap)
                if self._automatic_body_task() and self.drilling.status()['simulated_task_complete']:
                    self._journal('automatic_drilling_task_completed', basis='four anchored-hand dwells',
                                  **self.drilling.status())
                    self._advance_to(8)
                    self._phase('retreat_lower', 'All four drilling gestures detected. Step back with both arms clear for lowering')
                # Observe source frames, not repeated polling of one cached pose.
                # Location coverage does not authorise lowering or label screws complete.
                if self.work_visits is not None:
                    visited = self.work_visits.observe(
                        (snap.get("feature") or {}).get("t"), snap.get("position"))
                    if visited is not None:
                        self._journal("work_location_visited", location_index=visited,
                                      **self.work_visits.status())
            elif self.phase == "supported_release":
                self._require_pose("pose1_low")
                self._require_stationary()
                if self._stable(True, self.LOW_RELEASE_DWELL_S):
                    if self.cancel.is_set():
                        raise ValueError("Trial stopped before low-support release")
                    self._phase("releasing", "Releasing suction at verified stationary low support")
                    self._journal("automation_low_release_requested", dwell_s=self.LOW_RELEASE_DWELL_S)
                    action = self.rig.gripper_action("release", "BOTH", 0)
                    if not action.get("ok"):
                        raise ValueError("Low-support release failed; inspect rig and preserve attempt")
                    if self.cancel.is_set():
                        raise ValueError("Trial stopped during low-support release")
                    self._journal("automation_low_release_completed")
                    self.state.stop_session(outcome="completed")
                    self.automatic = False
                    self._phase("complete", "Run saved; suction released on the low support")
            if self.phase in ("loading", "retreat_lift", "retreat_lower") and self.clock() - self.since > self.WAIT_TIMEOUT_S:
                raise ValueError("Automatic step timed out")
        except Exception as exc:
            self.request_stop(str(exc))
            try:
                self.rig.robot_action("stop")
            except Exception as stop_exc:
                self.reason += f"; stop command failed: {stop_exc}. Use physical E-stop"
        finally:
            self.lock.release()

    def _automatic_body_task(self):
        return self.state.config.get('drilling_task', {}).get('automatic_completion') is True

    def _observe_simulated_drilling(self, snap):
        """Record hand dwells; the state machine separately owns retreat/motion."""
        data = snap.get("hand_tracking") or {}
        markers = data.get("optitrack_markers") or {}
        panel = data.get("panel") or {}
        try:
            body = data.get('anchored_body') or {}
            if self.state.config.get('helmet_body', {}).get('enabled'):
                if body.get('available') is not True:
                    raise ValueError(body.get('reason', 'Waiting for anchored body'))
                hands = {i: body['segments'][i]['position_optitrack_m'] for i in ('11', '15')}
                source_ids = (*body['source_ids'], markers['source_time_s'])
            else:
                hands = aligned_hands({"segments": data.get("xsens_hands", {})},
                                      self.state.config.get("simulated_drilling_alignment"))
                source_ids = (data['xsens_sample_counter'], markers['source_time_s'])
            fresh = (0 <= float(data["xsens_age_s"]) <= 0.15
                     and 0 <= float(markers["age_s"]) <= 0.15
                     and 0 <= float(panel["age_s"]) <= 0.15
                     and panel["source_time_s"] == markers["source_time_s"])
            if self.state.config.get('helmet_body', {}).get('enabled'):
                fresh = fresh and body['source_ids'][1] == panel['source_time_s']
            events = self.drilling.observe(
                self.clock(), markers.get("sets", {}).get(self.state.config.get('drilling_task', {}).get('marker_set', 'PANEL')), hands,
                source_ids=source_ids, fresh=fresh, task_active=True,
                panel_pose=panel if self.state.config.get('helmet_body', {}).get('enabled') else None)
        except (KeyError, TypeError, ValueError) as exc:
            self.drilling.observe(self.clock(), None, {}, source_ids=(0, 0), fresh=False, task_active=True)
            self.drilling.reason = str(exc)
            return
        for index in events:
            self._journal("simulated_drilling_marker_complete", marker_index=index,
                          **self.drilling.status())


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
            self._json({**self.state.snapshot(), "automation": self.guided.status()})
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
                "/api/protocol/complete", "/api/sync", "/api/session/stop",
            }
            if self.path in rig_paths:
                # rig control needs the key from any remote browser
                if remote and self.headers.get("X-Control-Key", "") != self.control_key:
                    return self._json({"error": "Bad or missing control key"}, 403)
                if self.guided.automatic and self.state.snapshot().get("recording"):
                    if self.path in {"/api/gripper", "/api/demo", "/api/cycle", "/api/xsens/reset"}:
                        raise ValueError("Abort the automatic trial before manual rig commands")
                    if self.path == "/api/robot":
                        if body.get("action") not in {"stop", "pause"}:
                            raise ValueError("Only stop/pause is allowed during an automatic trial")
                if self.path == "/api/gripper":
                    result = self.rig.gripper_action(
                        str(body.get("action")), str(body.get("channel", "BOTH")),
                        int(body.get("vacuum", 60)))
                elif self.path == "/api/robot":
                    if body.get("action") in {"stop", "pause"}:
                        self.guided.request_stop("Operator " + str(body.get("action")))
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
                        block_label=body.get("block_label"),
                        within_block_trial=body.get("within_block_trial"),
                        controller_condition=body.get("controller_condition"),
                        planned_event=body.get("planned_event"),
                        collection_mode=body.get("collection_mode", "model_development"),
                        motive_recording_reference=body.get("motive_recording_reference"),
                        video_recording_reference=body.get("video_recording_reference"),
                        vacuum=int(body.get("vacuum", 60)),
                        automatic=body.get("automatic") is True)
                elif self.path == "/api/protocol/arm":
                    result = self.guided.arm_step()
                elif self.path == "/api/protocol/complete":
                    result = self.guided.complete_step(int(body.get("vacuum", 60)))
                elif self.path == "/api/sync":
                    result = self.state.mark_sync_event()
                elif self.path == "/api/session/stop":
                    self.guided.request_stop("Trial aborted")
                    try:
                        stop_result = self.rig.robot_action("stop")
                    except Exception as exc:
                        stop_result = {"error": str(exc)}
                    result = self.state.stop_session(outcome="aborted")
                    result["robot_stop"] = stop_result
                    if stop_result.get("error"):
                        result["message"] += "; ROBOT STOP UNCONFIRMED — use physical E-stop"
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
            elif self.path == "/api/label":
                if self.guided.automatic:
                    raise ValueError("Automatic task phases are not ground-truth labels; annotate from video")
                result = self.state.set_label(body.get("label"))
            elif self.path == "/api/protocol/advance":
                raise ValueError("Direct advance is disabled; use the guarded protocol controls")
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
    parser.add_argument("--optitrack-data-port", type=int, default=1511,
                        help="NatNet multicast data port (default: 1511)")
    parser.add_argument("--segment", type=int, default=PELVIS)
    parser.add_argument("--out", default="data/xsens")
    parser.add_argument("--enable-automatic-trials", action="store_true",
                        help="enable the guarded automatic sequence for P-code participant studies and Q-code rehearsals")
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
        data_port=args.optitrack_data_port,
        monitor=optitrack_monitor,
        nominal_rate_hz=120.0,
    )
    optitrack_listener.start()
    stop = threading.Event()
    rig = RigControl(state.config["robot"]["host"],
                     state.config["robot"].get("dashboard_port", 29999))
    state.optitrack_monitor = optitrack_monitor
    state.rig = rig
    guided = AutomaticRunController(state, rig, enabled=args.enable_automatic_trials)
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

    def automation_loop() -> None:
        while not stop.wait(0.05):
            guided.tick()

    def hardware_loop() -> None:
        while not stop.wait(0.25):
            guided.refresh_health()

    threading.Thread(target=automation_loop, daemon=True).start()
    threading.Thread(target=hardware_loop, daemon=True).start()
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
        guided.request_stop("Service shutting down")
        stop.set()
        listener.stop()
        optitrack_listener.stop()
        server.server_close()
        if state.file is not None:
            state.file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
