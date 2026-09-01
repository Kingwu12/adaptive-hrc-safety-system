# Lab notes — 2026-08-12: Windows master, UR10 and Xsens bring-up

## Outcome

The Windows Xsens laptop was established as the intended master computer and
connected directly to the UR10 control box. Robot and Xsens telemetry were
verified without issuing robot motion commands. A four-point Xsens-only
absolute-position calibration was attempted and rejected because its spatial
error was too large for safety use. The next session will add OptiTrack as the
absolute position source while retaining Xsens for wearable kinematics.

## Windows and robot network

- Windows USB Ethernet adapter: `192.168.1.102/24`, no gateway or DNS.
- UR10 controller: `192.168.1.101/24`.
- Cable connected directly to the control-box bottom Ethernet port.
- Robot replied at approximately 1 ms.
- TCP ports verified open: Dashboard `29999`, URScript `30001`, RTDE `30004`.
- Wi-Fi remained available separately for internet/GitHub access.

Read-only status at bring-up:

- Robot: UR10 e-Series, PolyScope `5.9.3.1031212`.
- Robot mode: `RUNNING`.
- Safety mode: `NORMAL`.
- Program: `STOPPED user.urp`.
- RTDE receive: connected successfully.
- No motion, gripper, power, play, unlock, or speed-slider command was issued.

## Windows software setup

- Repository cloned from `https://github.com/Kingwu12/adaptive-hrc-safety-system`.
- Python 3.12 virtual environment created at `.venv`.
- Project dev dependencies and `ur-rtde 1.6.5` installed.
- Full test suite passed: 33 tests.
- Xsens reset listener was configured separately on TCP `9764`.

## Xsens streaming

MVN Analyze ran on the same Windows computer. Network Streamer was configured:

- Destination: `127.0.0.1`.
- UDP port: `9763`.
- Datagram: Position + Orientation (Quaternion), `MXTP02`.
- Pelvis segment ID: `1`.
- Observed rate: approximately 60 Hz.
- Real packets decoded successfully with the repository parser.

The wearer completed MVN N-pose calibration and used facing reference `W 287`.
Raw captures and capture stability are stored in
`data/calib/xsens_points.yaml`.

## Robot floor marks

Four points were read from pendant Tool Position screenshots using the selected
OnRobot TCP. The mean floor elevation was `-0.70240 m`; total Z range was
`10.27 mm`. Coordinates are stored in `data/calib/robot_points.yaml`.

The physical mark pairing is:

- Xsens point 1 -> robot mark D.
- Xsens point 2 -> robot mark C.
- Xsens point 3 -> robot mark A.
- Xsens point 4 -> robot mark B.

## Rejected Xsens-only calibration

A best-fit horizontal rigid transform was solved after correcting the point
ordering. Residuals were:

- Point 1: `171 mm`.
- Point 2: `95 mm`.
- Point 3: `184 mm`.
- Point 4: `310 mm`.
- RMS: `205 mm`.

This fit is explicitly marked rejected and must not be loaded by the live
controller. Pairwise distances differed by as much as approximately `414 mm`,
which cannot be explained by a rigid change of coordinates. MVN inertial
global-position drift and foot-placement variability are the likely causes.
No `configs/mocap_extrinsics.yaml` production calibration was generated.

## Revised sensor architecture

- OptiTrack/Motive: absolute operator pelvis position in the lab frame.
- Xsens: body posture, orientation, activity and wearable kinematics.
- UR RTDE: robot state.
- Windows: fusion, safety decision, logging and dashboard.
- Missing/stale OptiTrack position must force the conservative fail-safe state.
- Xsens global position must not be the safety-critical absolute separation.

## Next-session OptiTrack runbook

1. Calibrate the OptiTrack camera volume and set the ground plane/origin.
2. Attach a rigid cluster of preferably four markers to a pelvis belt/plate.
3. Define and refine an `operator_pelvis` rigid body in Motive.
4. Enable NatNet streaming to the Windows master.
5. Measure robot marks A-D in the OptiTrack frame with a tracked probe/rigid body.
6. Solve OptiTrack-to-robot extrinsics and validate on an independent fifth mark.
7. Target maximum validation error <=20 mm; document any larger accepted bound
   conservatively in the sensing uncertainty term.
8. Test static accuracy, dynamic path continuity, occlusion/staleness fail-safe,
   and end-to-end stopping latency before any participant or moving-robot trial.
9. Record OptiTrack and Xsens concurrently with synchronized timestamps.
10. Compare OptiTrack-only geometry with OptiTrack + Xsens activity features as
    an experimental ablation.

## End-of-session safe state

Operator must verify locally on the pendant before leaving:

- Program stopped.
- Arm parked safely.
- Cell clear.
- Robot returned to the lab-required Local/Remote and power state.
- MVN recording and network streaming stopped.
- Emergency-stop and normal shutdown procedures followed locally.

