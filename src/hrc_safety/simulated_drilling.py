"""Four-marker simulated drilling; observation only, with no robot commands."""
from __future__ import annotations

import math
import itertools
import numpy as np
from .body_tracking import rotation


class SimulatedDrilling:
    """Either hand must dwell at each of four PANEL markers, in any order.

    Both input streams must already be in OptiTrack metres. This detects a
    rehearsed gesture, not fastening. Reset at the beginning of every task.
    """

    def __init__(self, radius_m=0.12, dwell_s=2.0, max_gap_s=0.15):
        self.radius, self.dwell, self.max_gap = map(float, (radius_m, dwell_s, max_gap_s))
        if not all(math.isfinite(v) and v > 0 for v in (self.radius, self.dwell, self.max_gap)):
            raise ValueError("Positive finite radius, dwell and sample gap required")
        self.reset()

    def reset(self):
        self.completed = set()
        self.pending = {}
        self.last_t = None
        self.last_sources = None
        self.geometry = None
        self.corner_reference = None
        self.reason = "Waiting for aligned hands and four panel markers"
        self.distances = []
        self.fault = None

    def observe(self, t, markers, hands, *, source_ids, fresh, task_active, panel_pose=None):
        """Return new marker indices. Repeated frames never accumulate dwell."""
        if self.fault:
            self.reason = self.fault
            return []
        if not task_active or not fresh:
            self.pending.clear()
            self.last_t = self.last_sources = None
            self.reason = "Waiting for task stage" if not task_active else "Tracking unavailable or stale"
            return []
        try:
            t = float(t)
            source_ids = tuple(float(v) for v in source_ids)
            if len(source_ids) < 2 or not all(math.isfinite(v) for v in source_ids):
                raise ValueError("Invalid source frame identifiers")
            points = np.asarray(markers, dtype=float)
            hand_points = {str(k): np.asarray(v, dtype=float) for k, v in hands.items()}
            if (not math.isfinite(t) or points.shape != (4, 3) or not np.isfinite(points).all()
                    or not hand_points or any(p.shape != (3,) or not np.isfinite(p).all()
                                              for p in hand_points.values())):
                raise ValueError("Invalid positions")
            if panel_pose is not None:
                panel_r = rotation(panel_pose['rotation_xyzw'])
                panel_p = np.asarray(panel_pose['position'], dtype=float)
                if panel_p.shape != (3,) or not np.isfinite(panel_p).all():
                    raise ValueError("Invalid panel pose")
                local = (points - panel_p) @ panel_r
                if self.corner_reference is None:
                    self.corner_reference = local.copy()
                else:
                    # Preserve physical corner identity even if packet order
                    # changes on a symmetric rectangle. Global distances alone
                    # cannot distinguish those permutations.
                    matches = sorted((float(np.max(np.linalg.norm(local[list(order)] - self.corner_reference, axis=1))), order)
                                     for order in itertools.permutations(range(4)))
                    if matches[0][0] > .03 or matches[1][0] - matches[0][0] < .02:
                        self.fault = "Panel corner identity changed; restart observation"
                        raise ValueError(self.fault)
                    points = points[list(matches[0][1])]
            # The indexed distance matrix is invariant to rigid panel movement,
            # and detects most marker swaps or reconstructed geometry changes.
            geometry = np.linalg.norm(points[:, None] - points[None, :], axis=2)
            if min(geometry[i, j] for i in range(4) for j in range(i)) <= 2 * self.radius:
                raise ValueError("Panel marker regions overlap")
            if self.geometry is not None and np.max(np.abs(geometry - self.geometry)) > 0.03:
                self.fault = "Panel marker geometry changed; restart observation"
                raise ValueError("Panel marker geometry changed; restart observation")
        except (TypeError, ValueError):
            self.pending.clear()
            self.last_t = self.last_sources = None
            self.reason = "Invalid or changed marker/hand geometry"
            return []
        if self.geometry is None:
            self.geometry = geometry.copy()
        # Both streams must advance, not just our polling clock.
        if self.last_sources is not None and any(a <= b for a, b in zip(source_ids, self.last_sources)):
            if any(a < b for a, b in zip(source_ids, self.last_sources)):
                self.pending.clear()
                self.fault = self.reason = "Source clock reset; restart observation"
            return []
        if self.last_t is None or not 0 < t - self.last_t <= self.max_gap:
            self.pending.clear()
        self.last_t, self.last_sources = t, tuple(source_ids)
        self.distances = [min(float(np.linalg.norm(h - p)) for h in hand_points.values()) for p in points]
        hits = {}
        for hand, p in hand_points.items():
            distances = np.linalg.norm(points - p, axis=1)
            i = int(np.argmin(distances))
            if distances[i] <= self.radius and i not in self.completed:
                hits.setdefault(i, set()).add(hand)
        events = []
        for i in range(4):
            if i not in hits:
                self.pending.pop(i, None)
                continue
            old_hand, since = self.pending.get(i, (None, t))
            # Alternating hands cannot impersonate one continuous held gesture.
            hand = old_hand if old_hand in hits[i] else sorted(hits[i])[0]
            if hand != old_hand:
                since = t
            self.pending[i] = (hand, since)
            if t - since >= self.dwell:
                self.completed.add(i)
                self.pending.pop(i, None)
                events.append(i)
        self.reason = "Simulated drilling complete" if len(self.completed) == 4 else "Hold either hand near each panel marker"
        return events

    def status(self):
        return {"completed_markers": sorted(self.completed), "completed_count": len(self.completed),
                "total_markers": 4, "simulated_task_complete": len(self.completed) == 4,
                "nearest_hand_distances_m": self.distances, "reason": self.reason,
                "radius_m": self.radius, "dwell_s": self.dwell,
                "fault": self.fault,
                "corner_reference_local_m": None if self.corner_reference is None else self.corner_reference.tolist(),
                "fastening_verified": False}


def aligned_hands(frame, alignment):
    """Transform Xsens segment origins (11 right / 15 left) to OptiTrack.

    No identity fallback: the robot's OptiTrack extrinsics are a DIFFERENT
    transform. A current measured Xsens-to-OptiTrack alignment is required.
    """
    if (not alignment or alignment.get("accepted") is not True
            or alignment.get("from_frame") != "xsens" or alignment.get("to_frame") != "optitrack"
            or alignment.get("units") != "m"):
        raise ValueError("Current Xsens-to-OptiTrack alignment required")
    r = np.asarray(alignment["rotation"], dtype=float)
    t = np.asarray(alignment["translation"], dtype=float)
    if (r.shape != (3, 3) or t.shape != (3,) or not np.isfinite(r).all() or not np.isfinite(t).all()
            or not np.allclose(r.T @ r, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(r), 1)):
        raise ValueError("Invalid rigid alignment")
    segments = frame["segments"]
    result = {}
    for segment in ("11", "15"):
        p = np.asarray(segments[segment]["position_m"], dtype=float)
        if p.shape != (3,) or not np.isfinite(p).all():
            raise ValueError("Invalid hand position")
        result[segment] = (r @ p + t).tolist()
    return result
