import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.automation import CycleState, Interlocks, PanelAutomation
from hrc_safety.logging_schema import Command


def healthy(**changes):
    values = dict(head_fresh=True, xsens_fresh=True, panel_fresh=True,
                  robot_base_fresh=True, robot_normal=True,
                  emergency_chain_ok=True, grip_confirmed=True,
                  panel_slip_ok=True)
    values.update(changes)
    return Interlocks(**values)


def test_one_click_cycle_uses_supervisor_over_identical_task_sequence():
    a = PanelAutomation()
    assert a.start(healthy()).state == CycleState.LOAD
    o = a.tick(healthy(), Command.FULL_SPEED, 1.0)
    assert (o.state, o.task_motion, o.speed_fraction) == (CycleState.TRANSIT_UP, "raise", 1.0)
    o = a.tick(healthy(), Command.REDUCED_SPEED, .35)
    assert o.task_motion == "raise" and o.speed_fraction == .35
    o = a.tick(healthy(), Command.PROTECTIVE_STOP, 0)
    assert o.task_motion == "hold" and o.speed_fraction == 0
    o = a.tick(healthy(), Command.FULL_SPEED, 1, motion_complete=True)
    assert o.state == CycleState.HAND_GUIDE and o.task_motion == "compliant_hold"
    assert a.tick(healthy(), Command.FULL_SPEED, 1,
                  alignment_confirmed=True).state == CycleState.HOLD_BOLT
    assert a.tick(healthy(), Command.FULL_SPEED, 1,
                  fastening_confirmed=True).state == CycleState.RELEASE_RETRACT
    assert a.tick(healthy(), Command.FULL_SPEED, 1,
                  motion_complete=True).state == CycleState.COMPLETE


def test_every_live_interlock_failure_latches_fault_and_stop():
    fields = ("head_fresh", "xsens_fresh", "panel_fresh", "robot_base_fresh",
              "robot_normal", "emergency_chain_ok", "grip_confirmed",
              "panel_slip_ok")
    for field in fields:
        a = PanelAutomation(); a.start(healthy())
        a.tick(healthy(), Command.FULL_SPEED, 1)  # enter live TRANSIT_UP
        o = a.tick(healthy(**{field: False}), Command.FULL_SPEED, 1)
        assert o.state == CycleState.FAULT, field
        assert o.command == Command.PROTECTIVE_STOP and o.speed_fraction == 0


def test_preflight_failure_never_enters_live_cycle():
    a = PanelAutomation()
    o = a.start(healthy(head_fresh=False))
    assert o.state == CycleState.FAULT
    assert o.task_motion == "hold"
