"""Fail-safe state machine for the one-click ceiling-panel cycle.

Task sequencing is deterministic and identical across experimental rungs.
The selected controller supervises speed/stop; it never selects task poses.
Real hardware adapters must translate these outputs only after lab preflight.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .logging_schema import Command
from .panel_cycle import CollaborativeMode, Phase


class CycleState(str, Enum):
    IDLE = "idle"
    LOAD = Phase.LOAD.value
    TRANSIT_UP = Phase.TRANSIT_UP.value
    HAND_GUIDE = Phase.HAND_GUIDE.value
    HOLD_BOLT = Phase.HOLD_BOLT.value
    RELEASE_RETRACT = Phase.RELEASE_RETRACT.value
    COMPLETE = "complete"
    FAULT = "fault"


@dataclass(frozen=True)
class Interlocks:
    head_fresh: bool = False
    xsens_fresh: bool = False
    panel_fresh: bool = False
    robot_base_fresh: bool = False
    robot_normal: bool = False
    emergency_chain_ok: bool = False
    grip_confirmed: bool = False
    panel_slip_ok: bool = True

    @property
    def tracking_ok(self) -> bool:
        return self.head_fresh and self.xsens_fresh and self.panel_fresh

    @property
    def motion_ok(self) -> bool:
        return (self.tracking_ok and self.robot_base_fresh and self.robot_normal
                and self.emergency_chain_ok and self.grip_confirmed
                and self.panel_slip_ok)


@dataclass(frozen=True)
class CycleOutput:
    state: CycleState
    collaborative_mode: CollaborativeMode
    task_motion: str
    command: Command
    speed_fraction: float
    reason: str


_MODES = {
    CycleState.IDLE: CollaborativeMode.MONITORED_STOP,
    CycleState.LOAD: CollaborativeMode.MONITORED_STOP,
    CycleState.TRANSIT_UP: CollaborativeMode.SSM,
    CycleState.HAND_GUIDE: CollaborativeMode.HAND_GUIDE,
    CycleState.HOLD_BOLT: CollaborativeMode.MONITORED_STOP,
    CycleState.RELEASE_RETRACT: CollaborativeMode.SSM,
    CycleState.COMPLETE: CollaborativeMode.MONITORED_STOP,
    CycleState.FAULT: CollaborativeMode.MONITORED_STOP,
}


class PanelAutomation:
    """One-click task sequencer with independent safety-supervisor overlay."""

    def __init__(self) -> None:
        self.state = CycleState.IDLE
        self.fault_reason = ""

    def start(self, i: Interlocks) -> CycleOutput:
        if not (i.tracking_ok and i.robot_base_fresh and i.robot_normal
                and i.emergency_chain_ok):
            return self._fault("start preflight failed")
        self.state = CycleState.LOAD
        return self._held("ready for panel load")

    def tick(self, i: Interlocks, supervisor_command: Command,
             supervisor_speed: float, *, motion_complete: bool = False,
             alignment_confirmed: bool = False,
             fastening_confirmed: bool = False) -> CycleOutput:
        if self.state in (CycleState.IDLE, CycleState.COMPLETE, CycleState.FAULT):
            return self._held(self.fault_reason or self.state.value)
        if not i.tracking_ok:
            return self._fault("human/panel tracking stale")
        if not i.robot_base_fresh:
            return self._fault("robot-base reference stale")
        if not i.robot_normal or not i.emergency_chain_ok:
            return self._fault("robot safety state not normal")
        if not i.panel_slip_ok:
            return self._fault("panel slip exceeds calibrated tolerance")

        if self.state == CycleState.LOAD:
            if not i.grip_confirmed:
                return self._held("waiting for verified vacuum grip")
            self.state = CycleState.TRANSIT_UP
        elif not i.grip_confirmed:
            return self._fault("vacuum grip lost")

        if self.state == CycleState.TRANSIT_UP and motion_complete:
            self.state = CycleState.HAND_GUIDE
        elif self.state == CycleState.HAND_GUIDE and alignment_confirmed:
            self.state = CycleState.HOLD_BOLT
        elif self.state == CycleState.HOLD_BOLT and fastening_confirmed:
            self.state = CycleState.RELEASE_RETRACT
        elif self.state == CycleState.RELEASE_RETRACT and motion_complete:
            self.state = CycleState.COMPLETE
            return self._held("cycle complete; release requires confirmed ceiling support")

        mode = _MODES[self.state]
        if mode == CollaborativeMode.MONITORED_STOP:
            return self._held(f"{self.state.value}: monitored stop")
        if supervisor_command == Command.PROTECTIVE_STOP:
            return CycleOutput(self.state, mode, "hold", Command.PROTECTIVE_STOP,
                               0.0, "safety supervisor stop")
        speed = max(0.0, min(1.0, float(supervisor_speed)))
        motion = "raise" if self.state == CycleState.TRANSIT_UP else (
            "retract" if self.state == CycleState.RELEASE_RETRACT else "compliant_hold")
        return CycleOutput(self.state, mode, motion, supervisor_command, speed,
                           "task motion permitted by safety supervisor")

    def reset(self) -> CycleOutput:
        self.state = CycleState.IDLE
        self.fault_reason = ""
        return self._held("reset")

    def _fault(self, reason: str) -> CycleOutput:
        self.state = CycleState.FAULT
        self.fault_reason = reason
        return self._held(reason)

    def _held(self, reason: str) -> CycleOutput:
        return CycleOutput(self.state, _MODES[self.state], "hold",
                           Command.PROTECTIVE_STOP, 0.0, reason)
