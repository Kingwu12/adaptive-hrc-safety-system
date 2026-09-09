# Automatic experiment data capture

User correction, 9 September 2026: native MVN/Motive/video recording and filename confirmation are not part of the team's workflow. The system owns experiment capture. This supersedes earlier handoff instructions requiring those steps.

With tracking/calibration and the robot ready, press **Start trial**, then **Task complete** when the task is actually complete. The automatic cycle handles the intervening robot/gripper steps and saves on completion. Aborting preserves the recorded attempt. Consent, questionnaires and the planned movement cue still require people.

Start trial creates a unique session ID and sample/event filenames, records a local start timestamp, and captures streamed Xsens segments, OptiTrack tracking, robot telemetry, features, model/controller decisions and event metadata. Samples are saved at the backend capture cadence, nominally 60 Hz; this is not a raw packet archive at every upstream device's native rate. Each sample is flushed; completion or abort saves its manifest. No recording checkbox, filename field or shared-sync button is needed.

The manifest records `capture_mode: automatic_streams` and declares capture contents. External references default to null. The backend never invents `.mvn`, `.tak` or `.mp4` filenames, claims a camera recording, or claims that its automatic timestamp is a hardware/shared visual synchronization event. These external formats are optional sources, not requirements for automatic streamed-data capture. Independently assessing timing, event exposure and model performance remains separate from saving data successfully.

The launcher and dashboard detect older backends that still require manual recording steps. After deploying this code on the Central lab PC, restart with `Start-Lab.ps1`. This change has been tested locally with simulated hardware; it has not been deployed to the offline lab PC.

Verification: 266 Python tests passed with the UDP-listener test deselected; dashboard build and lint passed. Six integrated API-to-file cycles cover all three controllers in participant and rehearsal modes without native filenames, confirmation or sync requests. They verify the saved full 23-segment frames, robot telemetry, events, outcome, unique filenames, and absence of invented native-recording claims. Separate tests retain calibration, tracking, output and physical-sequence guards.
