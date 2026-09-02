# Xsens degraded-sensor note — 2026-09-02

During pilot data collection, the following Xsens sensors were reported dead:

- left foot
- left shoulder
- right upper leg

## Decision for the current HMM pilot

Continue collecting runs for the current four-feature upper HMM, provided the
dashboard shows both Xsens and OptiTrack streaming and the run passes the saved
quality checks.

The fitted observation vector is `[d, v_proj, v_lat_frac, a_proj]`. These
features are derived from the OptiTrack rigid-body position relative to the
live robot pose. The dashboard listens to Xsens segment 1 (pelvis) as the
wearable stream/timing source. None of the three failed limb sensors is used
directly in the fitted observation vector.

## Limitations

These sessions must be described as a degraded Xsens configuration. They must
not be presented as complete whole-body inertial capture and should not be used
to support claims about foot placement, shoulder motion, right-leg kinematics,
ergonomics, or a future limb/posture classifier without repairing the sensors
and recollecting the relevant data.

Before each participant, confirm that Xsens still supplies a stable pelvis
stream near the expected rate and that OptiTrack is fresh. If MVN cannot
produce the pelvis stream or the dashboard marks either source offline, do not
start the guided run.
