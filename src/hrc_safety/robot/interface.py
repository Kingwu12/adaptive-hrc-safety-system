"""Robot command interface.

MockRobot -- records commands; used by tests and the simulation runner.
URRobot   -- drives a real UR10 CB3 / URSim via ur-rtde (lazily imported so the core
             package has no hard dependency on the robot extra).

Command mapping (identical in URSim and on hardware):
  * full / reduced speed  -> RTDE speed-slider fraction (setSpeedSlider).
  * stop request          -> Dashboard 'pause' plus speed slider 0; resume -> 'play'.

LAB-REVIEW NOTE: Dashboard pause is not a safety-rated protective stop. It is suitable
only for URSim and controlled engineering bring-up. A participant run that relies on
SSM requires an independently validated safeguard output through the robot safety chain.
"""

from __future__ import annotations

from typing import Protocol

from ..logging_schema import Command


class RobotInterface(Protocol):
    """Minimal command surface both implementations satisfy."""

    def apply(self, command: Command, speed_fraction: float) -> None: ...

    def actual_tcp(self) -> list[float] | None:
        """Current tool-centre point [x, y, z] in the robot base frame.

        None means the pose is unavailable (no receive interface, or a read
        failed). Callers MUST treat None as 'do not trust separation' rather
        than falling back to a stale value.
        """
        ...


class MockRobot:
    """Records the sequence of commands without touching hardware."""

    def __init__(self, tcp: list[float] | None = None) -> None:
        self.history: list[tuple[Command, float]] = []
        self.stopped: bool = False
        self.speed_fraction: float = 1.0
        # Tests and the simulation runner can script a moving TCP by assigning
        # to this attribute between ticks.
        self.tcp: list[float] | None = list(tcp) if tcp is not None else None

    def actual_tcp(self) -> list[float] | None:
        return list(self.tcp) if self.tcp is not None else None

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
    """Real UR10 CB3 / URSim research driver via ur-rtde (imported lazily)."""

    def __init__(
        self,
        host: str,
        rtde_port: int = 30004,
        dashboard_port: int = 29999,
    ) -> None:
        # Lazy import so `pip install -e .` (no robot extra) still imports the pkg.
        try:
            from rtde_io import RTDEIOInterface
            from rtde_receive import RTDEReceiveInterface
            from dashboard_client import DashboardClient
        except ImportError as exc:  # pragma: no cover - requires the robot extra
            raise ImportError(
                "URRobot requires the 'robot' extra: pip install -e '.[robot]'"
            ) from exc

        self.host = host
        self._rtde = RTDEIOInterface(host)
        self._dashboard = DashboardClient(host)
        self._dashboard.connect()
        self._paused = False
        # Receive interface is what makes live separation real. Kept optional
        # so bring-up against a controller that refuses the extra RTDE client
        # degrades to an explicit None rather than a silent stale pose.
        try:
            self._recv = RTDEReceiveInterface(host)
        except Exception as exc:  # pragma: no cover - hardware dependent
            self._recv = None
            print(f"URRobot: RTDEReceiveInterface unavailable ({exc}); "
                  f"actual_tcp() will return None and live separation "
                  f"MUST NOT be trusted.")

    def actual_tcp(self) -> list[float] | None:  # pragma: no cover - hardware
        """Live TCP [x, y, z] in metres, robot base frame, or None."""
        if self._recv is None:
            return None
        try:
            pose = self._recv.getActualTCPPose()
        except Exception:
            return None
        if not pose or len(pose) < 3:
            return None
        return [float(pose[0]), float(pose[1]), float(pose[2])]

    def actual_q(self) -> list[float] | None:  # pragma: no cover - hardware
        """Live joint angles in radians, or None. Used to seed IK for the
        discrete GO UP / GO DOWN moves so they take a sane path."""
        if self._recv is None:
            return None
        try:
            q = self._recv.getActualQ()
        except Exception:
            return None
        return [float(x) for x in q] if q else None

    def apply(self, command: Command, speed_fraction: float) -> None:  # pragma: no cover
        if command == Command.PROTECTIVE_STOP:
            if not self._paused:
                try:
                    self._dashboard.pause()
                except RuntimeError:
                    pass  # no loaded program to pause; slider 0 below still halts
                self._paused = True
            self._rtde.setSpeedSlider(0.0)
            return
        # A speed command implies the cell should be running.
        if self._paused:
            try:
                self._dashboard.play()
            except RuntimeError:
                pass  # no loaded program (e.g. bare URSim); slider alone drives
            self._paused = False
        self._rtde.setSpeedSlider(max(0.0, min(1.0, float(speed_fraction))))
