"""NatNet bridge: Motive rigid-body stream -> 60 Hz pipeline ticks.

Design (docs/design/optitrack-bridge.md):
- ONE rigid body (torso cluster), position only.
- Decimate/hold Motive's 120-240 Hz stream to the pipeline tick rate.
- Drop-out: hold last position + staleness flag; > staleness_s stale means
  tracking loss -> caller falls back to worst-case (never optimistic).
- Optional rigid extrinsics (mocap frame -> robot-base frame), solved by
  scripts/calibrate_mocap.py and stored in configs/mocap_extrinsics.yaml.

Transport is injected: any source may call `on_sample(...)` (the vendored
Motive NatNetClient in vendor/, or a fake feed in tests).
"""
from __future__ import annotations

from dataclasses import dataclass
import threading

import numpy as np
import yaml


@dataclass(frozen=True)
class TickSample:
    """What the pipeline sees at each tick."""

    t: float                 # pipeline time (s, monotonic from first tick)
    position: np.ndarray     # (3,) in robot-base frame if extrinsics given
    stale: bool              # True => tracking loss; treat as worst-case
    age_s: float             # seconds since last received mocap sample
    motive_timestamp: float  # raw Motive timestamp of the held sample


def load_extrinsics(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Load (R, t) from a mocap_extrinsics.yaml written by calibrate_mocap."""
    with open(path) as fh:
        doc = yaml.safe_load(fh)
    R = np.asarray(doc["rotation"], dtype=float).reshape(3, 3)
    t = np.asarray(doc["translation"], dtype=float).reshape(3)
    return R, t


class MocapBridge:
    """Holds the latest rigid-body sample; emits one TickSample per tick.

    Wire-up:  source calls `on_sample(motive_ts, pos_xyz, tracked)` at the
    stream rate; the run loop calls `tick(now_s)` at sample_rate_hz and feeds
    the returned TickSample.position into FeatureExtractor.push (unless stale).
    """

    def __init__(
        self,
        sample_rate_hz: float = 60.0,
        staleness_s: float = 0.150,
        extrinsics: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> None:
        self.dt = 1.0 / float(sample_rate_hz)
        self.staleness_s = float(staleness_s)
        self._R, self._t = extrinsics if extrinsics else (None, None)
        self._last_pos: np.ndarray | None = None
        self._last_rx_wall: float | None = None
        self._last_motive_ts: float = float("nan")
        self._t0: float | None = None
        self._last_tick_t: float | None = None
        self._lock = threading.Lock()

    def on_sample(
        self, motive_ts: float, pos_xyz, tracked: bool, wall_time: float
    ) -> None:
        """Receive one rigid-body sample from the transport (any thread).

        Untracked frames (Motive still sends them) are ignored: holding the
        last TRACKED position is the documented drop-out behaviour.
        """
        if not tracked:
            return
        pos = np.asarray(pos_xyz, dtype=float).reshape(3)
        if not np.all(np.isfinite(pos)):
            return
        with self._lock:
            self._last_pos = pos.copy()
            self._last_motive_ts = float(motive_ts)
            self._last_rx_wall = float(wall_time)

    def tick(self, now_s: float) -> TickSample | None:
        """Emit the pipeline-facing sample for the tick at wall time now_s.

        Returns None until the first tracked sample has arrived (warm-up).
        Afterwards always returns a sample: held position + stale flag, so the
        caller can apply the worst-case fallback rather than silently pausing.
        """
        with self._lock:
            if self._last_pos is None or self._last_rx_wall is None:
                return None
            pos = self._last_pos.copy()
            last_rx_wall = self._last_rx_wall
            motive_ts = self._last_motive_ts
        if self._t0 is None:
            self._t0 = now_s
        elapsed = now_s - self._t0
        # The bridge contract is one call per configured pipeline tick. Keep
        # feature timestamps well-conditioned when scheduler timestamps are
        # equal/quantised (common on Windows and in deterministic bench tests).
        tick_t = (elapsed if self._last_tick_t is None else
                  max(elapsed, self._last_tick_t + self.dt))
        self._last_tick_t = tick_t
        age = max(0.0, now_s - last_rx_wall)
        if self._R is not None:
            pos = self._R @ pos + self._t
        return TickSample(
            t=tick_t,
            position=pos,
            stale=age > self.staleness_s,
            age_s=age,
            motive_timestamp=motive_ts,
        )
