"""Feature extraction from raw operator position samples.

CRITICAL DESIGN DECISION -- protective separation is measured to the robot's
OCCUPIED COLUMN, not to the TCP point. The UR10e holds a ceiling panel ~2.2 m
overhead; the physical hazard the operator can reach is the whole vertical column
of space the arm+panel occupies, from the ground under the TCP up to TCP height.
A human standing directly under the panel has ~0 m of protective separation even
though the TCP point is 2.2 m away. Measuring distance to the TCP point would
systematically over-report separation and silently defeat the safety argument.

Velocities and accelerations are estimated by a least-squares slope over a short
window rather than single-frame finite differences, for robustness to sensor jitter.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FeatureFrame:
    """One tick of derived features consumed by recognition and control.

    d          -- distance (m) to the nearest point of the robot's occupied column.
    d_dot      -- rate of change of d (m/s); negative means closing (== -v_proj).
    speed      -- operator speed magnitude (m/s).
    v_proj     -- velocity projected onto the unit vector toward the nearest column
                  point; POSITIVE means closing on the robot.
    v_lat_frac -- fraction of speed that is lateral (perpendicular to the closing
                  direction); ~1 while side-stepping/swaying, ~0 while walking in.
    a_proj     -- acceleration projected onto the closing direction (m/s^2).
    torso_facing -- cosine similarity of heading with the closing direction
                  (proxy for whether the operator faces the robot).
    """

    t: float
    d: float
    d_dot: float
    speed: float
    v_proj: float
    v_lat_frac: float
    a_proj: float
    torso_facing: float

    def as_vector(self) -> np.ndarray:
        """Observation vector fed to the Gaussian emission model.

        Order is fixed and shared by fit_emissions / step / viterbi.
        """
        return np.array(
            [self.d, self.v_proj, self.v_lat_frac, self.a_proj], dtype=float
        )


def nearest_column_point(p: np.ndarray, tcp: np.ndarray) -> np.ndarray:
    """Nearest point on the robot's occupied vertical column to operator point p.

    The column is the vertical segment from the ground under the TCP (z=0) up to
    the TCP height (z=tcp_z), at the TCP's (x, y).
    """
    x, y, z_top = float(tcp[0]), float(tcp[1]), float(tcp[2])
    z = min(max(float(p[2]), 0.0), z_top)  # clamp operator height onto the segment
    return np.array([x, y, z], dtype=float)


class FeatureExtractor:
    """Streaming feature extractor.

    Fed raw 3-D operator positions at a fixed sample rate; emits a FeatureFrame per
    push once enough history exists to estimate slopes.
    """

    def __init__(
        self,
        tcp_position,
        sample_rate_hz: float = 60.0,
        velocity_window: int = 5,
        accel_window: int = 3,
    ) -> None:
        self.tcp = np.asarray(tcp_position, dtype=float)
        self.dt = 1.0 / float(sample_rate_hz)
        self.velocity_window = int(velocity_window)
        self.accel_window = int(accel_window)
        maxlen = max(self.velocity_window, self.accel_window) + 1
        self._pos: deque[np.ndarray] = deque(maxlen=maxlen)
        self._t: deque[float] = deque(maxlen=maxlen)
        self._vel_hist: deque[float] = deque(maxlen=self.accel_window)
        self._t0: float | None = None

    @staticmethod
    def _slope(times: np.ndarray, values: np.ndarray) -> float:
        """Least-squares slope of values vs times (robust to jitter)."""
        if len(times) < 2:
            return 0.0
        t = times - times.mean()
        denom = float((t * t).sum())
        if denom == 0.0:
            return 0.0
        return float((t * (values - values.mean())).sum() / denom)

    def push(self, t: float, position) -> FeatureFrame | None:
        """Add a raw sample; return a FeatureFrame or None if warming up."""
        p = np.asarray(position, dtype=float)
        if self._t0 is None:
            self._t0 = t
        self._pos.append(p)
        self._t.append(t)

        near = nearest_column_point(p, self.tcp)
        to_robot = near - p
        d = float(np.linalg.norm(to_robot))
        u = to_robot / d if d > 1e-9 else np.zeros(3)  # unit vector toward robot

        if len(self._pos) < 2:
            return None

        times = np.array(self._t, dtype=float)
        pos = np.stack(self._pos, axis=0)

        # Per-axis least-squares velocity over the velocity window.
        n = min(self.velocity_window, len(times))
        vel = np.array(
            [self._slope(times[-n:], pos[-n:, ax]) for ax in range(3)], dtype=float
        )
        speed = float(np.linalg.norm(vel))
        v_proj = float(np.dot(vel, u))  # positive == closing on the robot
        d_dot = -v_proj  # closing (v_proj>0) shrinks d
        v_lat = vel - v_proj * u
        v_lat_mag = float(np.linalg.norm(v_lat))
        v_lat_frac = v_lat_mag / speed if speed > 1e-9 else 0.0

        # Acceleration = slope of recent projected-velocity history.
        self._vel_hist.append(v_proj)
        if len(self._vel_hist) >= 2:
            m = len(self._vel_hist)
            vt = times[-m:]
            a_proj = self._slope(vt, np.array(self._vel_hist, dtype=float))
        else:
            a_proj = 0.0

        heading = vel / speed if speed > 1e-9 else np.zeros(3)
        torso_facing = float(np.dot(heading, u))

        return FeatureFrame(
            t=t,
            d=d,
            d_dot=d_dot,
            speed=speed,
            v_proj=v_proj,
            v_lat_frac=v_lat_frac,
            a_proj=a_proj,
            torso_facing=torso_facing,
        )
