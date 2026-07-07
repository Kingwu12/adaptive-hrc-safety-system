"""Run a controller over a labelled trace (shared by the script and the tests).

One place owns 'feed a trace through the feature extractor and a controller', so the
simulation script and the smoke tests exercise the identical code path.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..features import FeatureExtractor, FeatureFrame
from ..logging_schema import DecisionRecord
from ..panel_cycle import CollaborativeMode
from .scenario import LoopTrace


@dataclass
class RunResult:
    frames: list[FeatureFrame]
    records: list[DecisionRecord]
    labels: list[str]  # ground-truth activity label aligned to each produced frame
    phases: list[str]  # cycle phase aligned to each produced frame ("" if none)
    robot_modes: list[str]  # certified robot mode aligned to each produced frame


def build_extractor(config: dict) -> FeatureExtractor:
    feat = config["features"]
    return FeatureExtractor(
        tcp_position=config["scenario"]["tcp_position"],
        sample_rate_hz=feat["sample_rate_hz"],
        velocity_window=feat["velocity_window"],
        accel_window=feat["accel_window"],
    )


_DEFAULT_MODE = CollaborativeMode.SSM.value


def _aligned(config: dict, trace: LoopTrace):
    """Extract feature frames with per-frame labels, phases, and certified robot modes.

    The extractor emits nothing on its warm-up sample; the dropped tick's label/phase/mode
    are dropped in lockstep so every list stays aligned one-to-one with `frames`. A trace
    with no phase/mode structure (legacy or pilot) defaults every tick to SSM / no phase.
    """
    extractor = build_extractor(config)
    n = len(trace.times)
    phases_src = trace.phases if trace.phases else [""] * n
    modes_src = trace.robot_modes if trace.robot_modes else [_DEFAULT_MODE] * n

    frames: list[FeatureFrame] = []
    labels: list[str] = []
    phases: list[str] = []
    modes: list[str] = []
    for t, pos, lab, phase, mode in zip(
        trace.times, trace.positions, trace.labels, phases_src, modes_src
    ):
        frame = extractor.push(float(t), pos)
        if frame is not None:
            frames.append(frame)
            labels.append(lab)
            phases.append(phase)
            modes.append(mode)
    return frames, labels, phases, modes


def extract_frames(config: dict, trace: LoopTrace) -> tuple[list[FeatureFrame], list[str]]:
    """Turn a raw trace into feature frames + aligned ground-truth activity labels."""
    frames, labels, _, _ = _aligned(config, trace)
    return frames, labels


def run_controller(config: dict, controller, trace: LoopTrace) -> RunResult:
    """Feed a trace through the extractor and a controller; collect decision records.

    Each tick's decision is made under the certified robot collaborative mode for that
    tick, so the controller's mode-aware floor (SSM / hand-guiding / monitored stop) is
    exercised exactly as it would be on live robot-reported mode.
    """
    frames, labels, phases, modes = _aligned(config, trace)
    records = [controller.decide(frame, robot_mode=mode) for frame, mode in zip(frames, modes)]
    return RunResult(
        frames=frames, records=records, labels=labels, phases=phases, robot_modes=modes
    )


def observation_matrix(frames: list[FeatureFrame]) -> np.ndarray:
    """Stack feature frames into an (T, n_features) observation matrix."""
    return np.stack([f.as_vector() for f in frames], axis=0)
