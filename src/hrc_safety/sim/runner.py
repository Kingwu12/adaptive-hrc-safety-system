"""Run a controller over a labelled trace (shared by the script and the tests).

One place owns 'feed a trace through the feature extractor and a controller', so the
simulation script and the smoke tests exercise the identical code path.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..features import FeatureExtractor, FeatureFrame
from ..logging_schema import DecisionRecord
from .scenario import LoopTrace


@dataclass
class RunResult:
    frames: list[FeatureFrame]
    records: list[DecisionRecord]
    labels: list[str]  # ground-truth label aligned to each produced frame


def build_extractor(config: dict) -> FeatureExtractor:
    feat = config["features"]
    return FeatureExtractor(
        tcp_position=config["scenario"]["tcp_position"],
        sample_rate_hz=feat["sample_rate_hz"],
        velocity_window=feat["velocity_window"],
        accel_window=feat["accel_window"],
    )


def extract_frames(config: dict, trace: LoopTrace) -> tuple[list[FeatureFrame], list[str]]:
    """Turn a raw trace into feature frames + aligned ground-truth labels.

    The extractor emits nothing on its warm-up sample; those labels are dropped so
    frames and labels stay aligned one-to-one.
    """
    extractor = build_extractor(config)
    frames: list[FeatureFrame] = []
    labels: list[str] = []
    for t, pos, lab in zip(trace.times, trace.positions, trace.labels):
        frame = extractor.push(float(t), pos)
        if frame is not None:
            frames.append(frame)
            labels.append(lab)
    return frames, labels


def run_controller(config: dict, controller, trace: LoopTrace) -> RunResult:
    """Feed a trace through the extractor and a controller; collect decision records."""
    frames, labels = extract_frames(config, trace)
    records = [controller.decide(frame) for frame in frames]
    return RunResult(frames=frames, records=records, labels=labels)


def observation_matrix(frames: list[FeatureFrame]) -> np.ndarray:
    """Stack feature frames into an (T, n_features) observation matrix."""
    return np.stack([f.as_vector() for f in frames], axis=0)
