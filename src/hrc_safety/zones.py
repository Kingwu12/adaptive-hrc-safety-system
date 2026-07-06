"""Speed-and-Separation Monitoring zone model (ISO/TS 15066).

Two concentric zones around the robot's occupied column:
  red    = S0            (protective separation; breach => protective stop)
  yellow = margin * S0   (warning band; reduced speed / adaptive behaviour)

S0 = K*T + C + Sa.

EXIT HYSTERESIS: entering a TIGHTER zone (red < yellow < green) is IMMEDIATE --
safety reactions never wait. LEAVING a zone requires clearing its boundary by an
extra hysteresis band. Without this, an operator hovering exactly on a boundary
makes the command flap every tick; that chatter would inflate the static
controller's interruption count and bias the comparison.
"""

from __future__ import annotations

from enum import IntEnum


class Zone(IntEnum):
    """Ordered so a larger value == a tighter (more dangerous) zone."""

    GREEN = 0
    YELLOW = 1
    RED = 2


class ZoneModel:
    """Stateful zone classifier with exit hysteresis."""

    def __init__(
        self,
        K: float,
        T: float,
        C: float,
        Sa: float,
        yellow_margin: float,
        hysteresis: float,
    ) -> None:
        self.K = float(K)
        self.T = float(T)
        self.C = float(C)
        self.Sa = float(Sa)
        self.yellow_margin = float(yellow_margin)
        self.hysteresis = float(hysteresis)
        self._zone: Zone = Zone.GREEN

    @property
    def S0(self) -> float:
        """ISO/TS 15066 protective separation distance."""
        return self.K * self.T + self.C + self.Sa

    @property
    def red_radius(self) -> float:
        return self.S0

    @property
    def yellow_radius(self) -> float:
        return self.yellow_margin * self.S0

    @property
    def zone(self) -> Zone:
        return self._zone

    def classify(self, d: float) -> Zone:
        """Instantaneous, memoryless zone for a distance (no hysteresis)."""
        if d <= self.red_radius:
            return Zone.RED
        if d <= self.yellow_radius:
            return Zone.YELLOW
        return Zone.GREEN

    def update(self, d: float) -> Zone:
        """Advance the stateful zone given a new distance.

        Tightening is immediate; loosening requires clearing the boundary by the
        hysteresis band.
        """
        raw = self.classify(d)

        if raw >= self._zone:
            # Same or tighter zone -> commit immediately.
            self._zone = raw
            return self._zone

        # Candidate is looser: only accept once we've cleared the boundary + band.
        if self._zone == Zone.RED:
            if d > self.red_radius + self.hysteresis:
                self._zone = Zone.YELLOW if d <= self.yellow_radius else Zone.GREEN
        elif self._zone == Zone.YELLOW:
            if d > self.yellow_radius + self.hysteresis:
                self._zone = Zone.GREEN

        # Re-check: leaving RED may land directly in GREEN if d cleared both bands.
        if self._zone == Zone.YELLOW and d > self.yellow_radius + self.hysteresis:
            self._zone = Zone.GREEN
        return self._zone

    def reset(self, zone: Zone = Zone.GREEN) -> None:
        self._zone = zone
