"""Observation-only coverage of four measured operator work locations.

Inputs are head positions in metres in the same calibrated frame as the
locations. Coverage is not evidence of fastening, clearance, or permission to
move. This module has no robot interface and does not advance a trial.
"""

from __future__ import annotations

import math
from itertools import combinations


class WorkLocationVisits:
    def __init__(self, locations, *, radius_m=0.25, dwell_s=2.0, max_gap_s=0.25):
        self.locations = tuple(tuple(float(v) for v in point) for point in locations)
        if (len(self.locations) != 4 or any(len(p) != 3 for p in self.locations)
                or not all(math.isfinite(v) for p in self.locations for v in p)):
            raise ValueError("Four finite measured head positions (x, y, z) are required")
        self.radius_m, self.dwell_s, self.max_gap_s = map(float, (radius_m, dwell_s, max_gap_s))
        if not all(math.isfinite(v) and v > 0 for v in
                   (self.radius_m, self.dwell_s, self.max_gap_s)):
            raise ValueError("Radius, dwell and maximum sample gap must be positive and finite")
        if any(math.dist(a, b) <= 2 * self.radius_m
               for a, b in combinations(self.locations, 2)):
            raise ValueError("Work-location regions must not overlap; reduce radius or check measurements")
        self.reset()

    def reset(self):
        """Begin a new task interval; visits never carry across trials."""
        self.visited = set()
        self.candidate = None
        self.since = None
        self.last_t = None

    def observe(self, t, position, *, tracked=True, task_active=True):
        """Return a newly visited zero-based location, or None.

        A continuous dwell is required. Missing tracking, invalid positions,
        repeated/backward timestamps and sample gaps reset the pending dwell.
        Previously completed visits remain observations until reset().
        """
        try:
            t = float(t)
            point = tuple(float(v) for v in position)
            valid = (tracked and task_active and math.isfinite(t) and len(point) == 3
                     and all(math.isfinite(v) for v in point))
        except (TypeError, ValueError):
            valid = False
        if not valid:
            self.candidate = self.since = self.last_t = None
            return None
        continuous = self.last_t is not None and 0 < t - self.last_t <= self.max_gap_s
        self.last_t = t
        if not continuous:
            self.candidate = self.since = None
        hit = next((i for i, centre in enumerate(self.locations)
                    if i not in self.visited and math.dist(point, centre) <= self.radius_m), None)
        if hit is None:
            self.candidate = self.since = None
            return None
        if hit != self.candidate:
            self.candidate, self.since = hit, t
        if t - self.since >= self.dwell_s:
            self.visited.add(hit)
            self.candidate = self.since = None
            return hit
        return None

    def status(self):
        return {"visited_locations": sorted(self.visited), "visited_count": len(self.visited),
                "total_locations": 4, "all_locations_visited": len(self.visited) == 4,
                "evidence": "operator location visits only", "fastening_verified": False}
