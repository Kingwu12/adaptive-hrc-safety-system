"""Panel-Cycle vocabulary -- the SINGLE owner of the sem-2 v2 task structure.

The experimental task is one repeating **Panel Cycle** of ceiling-panel installation,
human + robot. The robot is a lifting/holding jack with a releasable gripper/vacuum
end-effector -- nothing is ever bolted to the robot. The human is loader, aligner, and
bolter. Five phases repeat every cycle:

    LOAD             P1  arm lowered to waist; human slides the panel onto the plate.
    TRANSIT_UP       P2  robot lifts + aligns the panel to the frame while the human
                         tends the shared workspace (bolt gun, platform). MEASURE.
    HAND_GUIDE       P3  human nudges the compliantly-held panel a few mm by hand --
                         genuine contact, ISO/TS 15066 hand-guiding mode. MEASURE.
    HOLD_BOLT        P4  human drives bolts into the CEILING while the robot holds dead
                         still (safety-rated monitored stop). NOT a measurement window.
    RELEASE_RETRACT  P5  robot releases + lowers while the human finishes / descends.
                         MEASURE.

Two orthogonal facts travel per tick and must never be conflated:

  * the CYCLE PHASE (`Phase`) -- which task step we are in; drives per-phase reporting.
  * the configured/controller-reported COLLABORATIVE MODE (`CollaborativeMode`) --
    never a learned inference. The deterministic command bound is mode-aware; the
    learned layer is not. A mode name alone is not evidence of a safety-rated function.

This module is domain-level (imported by controllers, metrics, and the scenario) so the
phase/mode names have exactly ONE definition. Adapting the scenario or a controller to a
new phase means editing this file, not re-typing strings in three places.
"""

from __future__ import annotations

from enum import Enum


class CollaborativeMode(str, Enum):
    """Configured collaborative operating mode used by the prototype.

    The prototype command bound keys its behaviour off this signal:
      SSM            -- speed-and-separation monitoring: the dynamic envelope + the
                        fixed-RED hard stop govern (P2 transit, P5 retract).
      HAND_GUIDE     -- intended hand-guiding: the robot holds the panel compliantly and
                        the human guides it. Contact may be permitted only after the real
                        robot mode, force limits, tooling and task are risk-assessed and
                        validated; a software enum does not establish that permission.
      MONITORED_STOP -- safety-rated monitored stop: the robot is commanded dead still
                        while the human works at close range (P1 load, P4 bolt).
    """

    SSM = "ssm"
    HAND_GUIDE = "hand_guide"
    MONITORED_STOP = "monitored_stop"


class Phase(str, Enum):
    """One step of the repeating Panel Cycle."""

    LOAD = "load"
    TRANSIT_UP = "transit_up"
    HAND_GUIDE = "hand_guide"
    HOLD_BOLT = "hold_bolt"
    RELEASE_RETRACT = "release_retract"


# Display / iteration order (P1 -> P5).
PHASES: tuple[str, ...] = (
    Phase.LOAD.value,
    Phase.TRANSIT_UP.value,
    Phase.HAND_GUIDE.value,
    Phase.HOLD_BOLT.value,
    Phase.RELEASE_RETRACT.value,
)

# Phases whose static-vs-adaptive divergence is what the study measures.
#   P2/P3/P5 are measurement windows; P1 (arm parked) and P4 (SMS hold, static==adaptive)
#   are NOT. Measuring the P4 hold was the exact confusion the v2 redesign resolved.
MEASUREMENT_WINDOWS: tuple[str, ...] = (
    Phase.TRANSIT_UP.value,
    Phase.HAND_GUIDE.value,
    Phase.RELEASE_RETRACT.value,
)

# Phases governed by speed-and-separation monitoring, where MINIMUM SEPARATION is a
# genuine safety quantity (higher = safer). In HAND_GUIDE contact is intended, so ~0 m of
# separation there is by design, not a breach -- it is excluded from the separation metric.
SSM_WINDOWS: tuple[str, ...] = (
    Phase.TRANSIT_UP.value,
    Phase.RELEASE_RETRACT.value,
)


def is_measurement_window(phase: str) -> bool:
    """True if the phase is a static-vs-adaptive measurement window (P2/P3/P5)."""
    return phase in MEASUREMENT_WINDOWS
