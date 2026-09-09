# Work-location observations

The automatic trial backend can record four distinct operator work-location
visits during its task stage. The dashboard displays the count when configured.
This observes activity only: it does not verify screws, advance the task, lower
the arm, release suction, or enable automation.

The optional `work_location_observation` configuration uses `frame: robot_base`,
`units: m`, and `head_positions`: four measured three-component head positions
at the work locations. These are the same coordinates as the dashboard's
OptiTrack head position, not screw coordinates. No lab positions are fabricated
or supplied by default. A panel rigid-body pose alone does not specify them.

Optional settings are `radius_m` (default 0.25), `dwell_s` (2.0), and
`max_gap_s` (0.25). Regions must not overlap. Defaults are initial detector
parameters, not validated lab thresholds. Invalid frames and geometry are
rejected. Missing configuration leaves observation unconfigured.

Each location needs continuous valid source frames through the dwell. Duplicate
or backward timestamps, missing positions and long gaps reset the pending dwell.
Visits reset at each trial start. New visits generate `work_location_visited`
events with the zero-based location index and coverage count. Coverage is never
written as fastening verification or HMM ground truth. Existing task confirmation
and motion checks remain in place.

Tests use synthetic coordinates and fake robot interfaces; they establish
software behavior only. The running hardware backend has not been restarted as
part of this integration.
