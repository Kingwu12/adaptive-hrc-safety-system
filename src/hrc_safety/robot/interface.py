"""Robot command interface.

MockRobot -- records commands; used by tests and the simulation runner.
URRobot   -- drives a real UR10e / URSim via ur-rtde (lazily imported so the core
             package has no hard dependency on the robot extra).

Command mapping (identical in URSim and on hardware):
  * full / reduced speed  -> RTDE speed-slider fraction (setSpeedSlider).
  * protective stop       -> Dashboard 'pause'; resume -> Dashboard 'play'.

LAB-REVIEW NOTE: driving the protective stop through the Dashboard pause is fine
for URSim and bring-up, but a REAL safeguard stop must be wired through the robot's
safety I/O (configurable safety inputs), not the Dashboard, per the lab safety review.
"""

from __future__ import annotations

from typing import Protocol

from ..logging_schema import Command


class RobotInterface(Protocol):
    """Minimal command surface both implementations satisfy."""

    def apply(self, command: Command, speed_fraction: float) -> None: ...


class MockRobot:
    """Records the sequence of commands without touching hardware."""

    def __init__(self) -> None:
        self.history: list[tuple[Command, float]] = []
        self.stopped: bool = False
        self.speed_fraction: float = 1.0

    def apply(self, command: Command, speed_fraction: float) -> None:
        self.history.append((command, float(speed_fraction)))
        if command == Command.PROTECTIVE_STOP:
            self.stopped = True
            self.speed_fraction = 0.0
        else:
            self.stopped = False
            self.speed_fraction = float(speed_fraction)

    @property
    def stop_count(self) -> int:
        return sum(1 for c, _ in self.history if c == Command.PROTECTIVE_STOP)


class URRobot:
    """Real UR10e / URSim driver via ur-rtde (imported lazily)."""

    def __init__(
        self,
        host: str,
        rtde_port: int = 30004,
        dashboard_port: int = 29999,
    ) -> None:
        # Lazy import so `pip install -e .` (no robot extra) still imports the pkg.
        try:
            from rtde_control import RTDEControlInterface
            from dashboard_client import DashboardClient
        except ImportError as exc:  # pragma: no cover - requires the robot extra
            raise ImportError(
                "URRobot requires the 'robot' extra: pip install -e '.[robot]'"
            ) from exc

        self.host = host
        self._rtde = RTDEControlInterface(host)
        self._dashboard = DashboardClient(host)
        self._dashboard.connect()
        self._paused = False

    def apply(self, command: Command, speed_fraction: float) -> None:  # pragma: no cover
        if command == Command.PROTECTIVE_STOP:
            if not self._paused:
                self._dashboard.pause()
                self._paused = True
            return
        # A speed command implies the cell should be running.
        if self._paused:
            self._dashboard.play()
            self._paused = False
        self._rtde.setSpeedSlider(max(0.0, min(1.0, float(speed_fraction))))
