# Automatic panel trial: qualification handoff

Status: software implementation, not physical participant release. The server
rejects automatic participant runs. Only Q-code qualification can opt in.
Existing participant runs remain explicitly operator-confirmed; do not pool
those timings with future automatic runs without addressing the protocol change.

## What is implemented

One server-owned cycle, independent of which of the three safety controllers is
assigned. Browser refresh does not restart or advance the cycle.

1. Press **Start trial — suction turns on** with its assigned controller/event
   and unique native files. After verifying the robot is stationary at the low
   pose, suction is off initially and the operator is clear, this single action
   starts recording and enables loading suction. There is no separate suction
   confirmation. Starting the service alone still never activates the gripper.
2. Record the shared sync marker while suction is already on. Missing sync blocks
   advancement and motion, not suction availability. A failed suction start
   latches a fault and retains the recording for abort/save; it never vents.
3. Participant approaches and places the panel against both cups. The robot stays
   stationary. Suction is already running; both measured pressures must remain
   above the seal threshold before the dashboard instructs release and retreat.
4. Once tracking reports separation beyond the configured launch clearance for
   a sustained dwell, lift automatically. The selected research controller owns
   speed/stop during that same trajectory; the sequencer does not impose its
   launch-clearance condition throughout the scored motion window.
5. At the verified top pose, suction stays on. Participant approaches and performs
   the agreed task. Operator confirms **Task complete**; the system cannot sense
   successful assembly from vacuum or the HMM.
6. Sustained retreat triggers automatic lowering. Suction stays on.
7. At the verified low pose, the participant supports the panel. Arm and confirm
   **Panel supported — release & save**. There is no unattended repeat loop.

Only supported release retains the deliberate two-press suction confirmation.
The safety comparison still exercises controller response during motion.

## Run software checks without hardware

From the repository root:

```sh
.venv/bin/python -m pytest tests/test_automatic_trials.py tests/test_dashboard_server.py
```

Tests use fake hardware only. They cover the complete sequence, independent
clearance and seal dwells, one-sided grip loss, invalid distance, stale readings,
failed controller output, timeouts, cancellation, supported-only release,
watchdog setup, target-pose checks, remote abort authentication, and API bypasses.

## Enable a controlled lab rehearsal

Only after the team has set up the physical safeguards, known payload/centre of
gravity, supported loading/release positions and marked participant route:

```sh
python scripts/dashboard_server.py --share --enable-research-speed-output --enable-automatic-trials
```

Open **Qualification** in the dashboard. It identifies this as automatic mode;
Q-codes stay separate from participant results and model-development data.
Starting the service alone never activates suction or motion.

## Fault behaviour and limitations

- Missing/invalid/stale tracking, stale robot/gripper health, grip loss after
  acquisition, failed/stale controller output or timeout latches the trial fault.
  A stop request does not wait for the task lock. No automatic restart or venting.
- Faults leave suction commanded on; this is not proof the panel remains held.
  Use the independent emergency procedure and physical panel retention/support.
- Stop/pause and abort remain available. Other manual robot, gripper, demo and
  direct-advance commands are blocked while an automatic recording is active.
  Abort preserves the attempt even if the stop connection fails, and reports that
  failure. A stop command acknowledgement is not measured zero velocity.
- Automatic moves use RTDE asynchronous moveJ, a host guard loop and robot-side
  communication watchdog. These are research controls, **not safety-rated**.
  [RTDE asynchronous move reference](https://sdurobotics.gitlab.io/ur_rtde/pages/examples/basic_motion/move_async_example.html).
- Development settings: seal >=500 permille on both channels for 1 s; launch
  clearance dwell 2 s; health age <=2 s including IO time; controller freshness
  <=0.5 s; motion timeout 90 s; acquisition/retreat timeout 120 s; watchdog 2 Hz.
  Supported release also requires RTDE source freshness <=0.25 s and all joint
  velocities <=0.005 rad/s, plus the existing low-pose and explicit support checks.
  These are unvalidated engineering settings, not measured stopping guarantees.
  SSH-based vacuum polling is slow and must be measured under final lab load.
- Clearance currently uses the tracked head proxy. It does not establish whole
  body/hand clearance, panel alignment, attachment strength, weight or slip.
  Vacuum is seal evidence only; payload must be measured/configured separately.

## Data and acceptance before participant release

Samples, events and manifests identify `execution_mode`. Automatic task phases
remain `unlabelled`: they must not train or validate the HMM as if independently
observed. The event journal records automation transitions and the commanded lift
window. That window is not measured intrusion onset or proof the robot moved;
derive actual motion/event timing from synchronized robot telemetry and video.

Automatic capture grading checks completion, recording quality and the assigned
event-window labels, not model accuracy or safety. Missing/aborted manifests fail
completion. Preserve native MVN, Motive and video alongside the dashboard trace.

Before lifting the participant gate, witness the full cycle on the actual setup
under all three conditions, repeat grip/communication/tracking/stop fault tests,
verify bounded stop response, hand/body and swept-volume protection, payload,
panel retention and release support, and confirm cues do not invite approach
before the arm is stationary. Record the measured results and responsible reviewer.
Reconcile the protocol/analysis freeze with this automation version; do not mark
the existing research-readiness gates complete from software tests.

## Software verification, 9 September 2026

- v1 baseline: 153 Python tests passed, including 30 automatic-trial cases.
- v2 adds trial-start suction without another confirmation, plus regressions for
  missing sync, duplicate starts, startup cancellation, failed suction/telemetry,
  and moving/wrong-pose startup. Full suite: 160 passed (37 automatic-trial cases).
- Dashboard lint and production build passed. Browser inspection confirmed the
  study/qualification separation, one current action, and offline robot status.
- Standalone `tsc --noEmit` remains blocked by missing Cloudflare worker type
  declarations in unchanged `db/index.ts` and `worker/index.ts`; this is not a
  clean whole-project type-check receipt. The dashboard build and lint did pass.
- Through the running dashboard proxy, `/api/status` reported automatic mode
  available but inactive and qualification-only. An automatic participant start
  returned HTTP 400 before any hardware action.
- No robot movement, suction action or real participant recording was performed
  for these checks. Physical timing and performance are still unmeasured here.
