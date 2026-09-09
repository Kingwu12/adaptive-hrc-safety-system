"""Read-only controller witnesses. Shadow decisions never reach robot outputs."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from .analysis import build_controller

CONTROLLERS = {"fixed zone": "fixed_zone", "reactive SSM": "dynamic_ssm",
               "predictive SSM": "adaptive"}


def live_tcp_position(telemetry):
    """Accept only a finite live robot pose with a fresh RTDE source clock."""
    pose = telemetry.get('actual_tcp_pose')
    age = telemetry.get('source_age_s')
    stamp = telemetry.get('source_timestamp_s')
    if (telemetry.get('available') is True and isinstance(pose, (list, tuple))
            and len(pose) == 6
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in pose)
            and isinstance(age, (int, float)) and 0 <= age <= .25
            and isinstance(stamp, (int, float)) and math.isfinite(stamp)):
        return list(pose[:3])
    return None


class EventExposure:
    """Observe cued-window exposure, never invent human ground truth or actuate."""
    def __init__(self, config):
        z = config['zones']
        self.red = z['K'] * z['T'] + z['C'] + z['Sa']
        self.min_closing = config['horizon']['min_closing_speed']
        self.motion_samples = 0
        self.rapid_samples = 0
        self.boundary_samples = 0
        self.last_source = None
        self.moving = False

    def observe(self, feature, telemetry, in_window):
        self.moving = False
        qd = telemetry.get('actual_qd')
        age = telemetry.get('source_age_s')
        source = telemetry.get('source_timestamp_s')
        if (telemetry.get('available') is not True or not isinstance(qd, list)
                or len(qd) != 6 or not all(isinstance(v, (int,float)) and math.isfinite(v) for v in qd)
                or not isinstance(age, (int,float)) or not 0 <= age <= .25
                or not isinstance(source, (int,float)) or not math.isfinite(source)):
            return
        self.moving = max(map(abs,qd)) > .005
        if self.last_source is not None and source <= self.last_source:
            return
        self.last_source = source
        if not in_window or not isinstance(feature, dict):
            return
        d, v = feature.get('d'), feature.get('v_proj')
        if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (d,v)):
            return
        if self.moving:
            self.motion_samples += 1
            self.rapid_samples += int(v >= self.min_closing)
            self.boundary_samples += int(d <= self.red)

    def status(self, planned_event):
        issue = None
        if planned_event in ('rapid intrusion','distractor') and self.motion_samples == 0:
            issue = 'No measured robot motion in the cued event window; review the trial.'
        elif planned_event == 'rapid intrusion' and self.rapid_samples < 2:
            issue = 'Rapid closing was not evidenced during the moving event window; review the cue and video.'
        elif planned_event == 'distractor' and (self.rapid_samples >= 2 or self.boundary_samples >= 2):
            issue = 'The distractor window includes rapid closing or boundary entry; review the event annotation.'
        return {'motion_samples':self.motion_samples, 'rapid_closing_samples':self.rapid_samples,
                'boundary_entry_samples':self.boundary_samples, 'robot_moving':self.moving,
                'review_reason':issue, 'ground_truth_verified':False,
                'basis':'Kinematic diagnostic within the planned window; independent annotation still required.'}


def model_health(hmm, sample_rate_hz=60.0):
    exit_probability = np.maximum(0.0, 1.0 - np.diag(hmm.A))
    dwell = [None if p < 1e-12 else float(1 / p / sample_rate_hz)
             for p in exit_probability]
    warnings = []
    if any(p < 1e-12 for p in exit_probability):
        warnings.append("Model transitions are effectively locked; use a development candidate and validate causal phase changes before a new study release.")
    return {"warnings": warnings, "expected_state_dwell_s": dwell,
            "interpretation": "Transition-prior dwell, not measured recognition latency."}


class ControllerComparison:
    """Independent beliefs and hysteresis for the same recorded input stream."""
    def __init__(self, config, fitted):
        self.controllers = {name: build_controller(key, config, fitted)
                            for name, key in CONTROLLERS.items()}

    def decide(self, frame):
        result = {}
        for name, controller in self.controllers.items():
            decision = controller.decide(frame, robot_mode="ssm")
            result[name] = {"speed_fraction": decision.speed_fraction,
                            "command": decision.command, "rule": decision.rule,
                            "inferred_state": decision.inferred_state,
                            "shadow_only": True}
        return result


def release_fingerprint(root: Path, model_hash: str, config: dict):
    """Identify the actual files, including uncommitted changes, at run start."""
    import json
    paths = ["scripts/dashboard_server.py", "src/hrc_safety/controllers/controllers.py",
             "src/hrc_safety/features.py", "src/hrc_safety/horizon.py",
             "src/hrc_safety/lhmm/upper.py", "src/hrc_safety/envelope.py",
             "src/hrc_safety/zones.py", "src/hrc_safety/experiment_diagnostics.py",
             "dashboard/app/page.tsx", "configs/analysis_plan.yaml",
             "configs/mocap_extrinsics.yaml", "data/taught_poses.json"]
    paths = sorted(set(paths) | {p.relative_to(root).as_posix()
                                for p in (root / 'src/hrc_safety').rglob('*.py')})
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
             if (root / name).is_file() else None for name in paths}
    body = {"model_sha256": model_hash, "files": files, "config": config}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {**body, "sha256": digest, "final_data_approved": False}
