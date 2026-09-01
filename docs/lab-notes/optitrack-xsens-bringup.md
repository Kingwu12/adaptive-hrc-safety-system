# OptiTrack + Xsens + UR bring-up

## Motive assets

Create rigid bodies with stable, unique IDs (the names are for operators; the
IDs are what the program uses):

- `HUMAN_HEAD` — one asymmetric marker cluster attached firmly to the top of
  the participant's head; record its numeric rigid-body ID.
- `ROBOT_BASE`, `ROBOT_SHOULDER`, `ROBOT_ELBOW`, `ROBOT_WRIST`, `ROBOT_TOOL`
  (and optionally `ROBOT_PANEL`) — record all numeric IDs.

The eight cameras define the tracking volume; they are not configured in this
program. Calibrate all cameras and set Motive's ground plane first. Avoid
collinear/symmetric marker layouts and confirm every rigid body remains tracked
through the complete arm cycle.

In Motive, enable NatNet streaming. Use multicast when Motive and this program
are on the same subnet; use unicast if multicast is blocked. Copy the official
NatNet SDK Python sample `NatNetClient.py` to `vendor/`.

## Coordinate calibration

Measure at least four non-coplanar/common points in both OptiTrack and UR base
coordinates, solve the transform, and validate against an unused fifth point:

```powershell
python scripts/calibrate_mocap.py --mocap data/calib/optitrack_points.yaml `
  --robot data/calib/robot_points.yaml --out configs/mocap_extrinsics.yaml
```

Do not command the real robot until the independent validation error and the
stationary/no-motion uncertainty test are accepted for the experiment.

## Bench test (no robot motion)

Start with the mock robot. Replace the example IPs and IDs:

```powershell
python scripts/live_run.py --source fused --robot mock `
  --motive-host 192.168.10.2 --local-ip 192.168.10.3 `
  --head-rigid-body 10 --robot-rigid-bodies 20,21,22,23,24,25 `
  --xsens-port 9763 --extrinsics configs/mocap_extrinsics.yaml `
  --record data/mocap/bench.jsonl
```

Cover the head cluster for longer than 150 ms and confirm `TRACKING LOST ->
protective_stop`. Move each robot cluster and inspect its matching ID in the
JSONL. Xsens data appears under `xsens`; OptiTrack head position remains the
absolute safety input.

## Real-arm gate

Only after the mock test, extrinsic validation, network latency/stopping-time
measurement, and physical safety review:

```powershell
python scripts/live_run.py --source fused --robot ur --host 192.168.1.101 `
  --motive-host 192.168.10.2 --local-ip 192.168.10.3 `
  --head-rigid-body 10 --robot-rigid-bodies 20,21,22,23,24,25 `
  --extrinsics configs/mocap_extrinsics.yaml --record data/mocap/trial01.jsonl
```

Exiting or losing OptiTrack leaves the robot stopped. Dashboard pause/play is
research control integration, not a certified safeguard; retain the pendant,
emergency stop, risk assessment, and safety-rated protective system.
