# Automatic panel trials: participant and rehearsal handoff

## Shared participant/rehearsal engine with automatic capture (v6, 2026-09-09)

`automatic-panel-v6-stream-capture` runs the same guarded sequence in
Participant study (P-codes) and Qualification (Q-codes). The earlier Q-only
restriction was an administrative software gate, not a different physical
algorithm. Collection mode determines data classification; it does not weaken
grip, tracking, pose, supported-release, stop or watchdog checks.

Run `Setup-Lab.cmd` once on a new checkout. Before a session, double-click
`Check-Lab.cmd`, then `Start-Lab.cmd`, select the desired collection mode, and
press Start trial. Sample and event files are created automatically;
observed task completion remains explicit. No native recording, filename entry
or manual shared-sync marker is required. The dashboard reports if an older
rehearsal-only backend is still running instead of silently switching to manual.
The CMD launchers apply `ExecutionPolicy Bypass` to one child process. This handles
ordinary PowerShell script restrictions; administrator-managed Group Policy still
takes precedence. The original Windows policy error has not been recovered, so
this is not proof that PowerShell caused the lab failure.

The launcher never terminates existing processes. It reuses a compatible backend
or reports the exact mismatch. A timeout or failed port inspection means unknown
state, never evidence that no trial is active. Resolve the rig/recording state
before deliberately shutting down an older service. The launcher checks the
startup-time backend source SHA-256 and process ID through both ports 8765 and
3000 before printing `SERVICES READY`. This is a software check, not physical
qualification. See [Windows diagnosis and repair](windows-startup-repair.md).

This implementation was tested locally with simulated hardware and a real local
HTTP service. It has not been deployed to or physically checked on the offline
lab PC. Earlier operator-confirmed data stays unchanged and separately identified.

## Windows revision: supported low release (2026-09-09)

`automatic-panel-v4-supported-low` replaces the automatic mode's final manual
release confirmation. The operator confirmed that the panel rests on the rigid
gripper support at `pose1_low` with vacuum off. This revision is specific to that
support arrangement; it does not infer panel support from suction pressure.
After reaching the low pose, the runner verifies stationary telemetry and the low
joint pose throughout a two-second dwell, then commands release once and saves.
Tracking/health loss, pose drift, motion, cancellation or release failure latches
a fault. A failed release is not retried or counted as a completed trial.
The support assumption and dwell are included in the versioned task contract.
Manual mode is unchanged. The instructions below describe this supported
automatic release revision.

The supported-low release sequence is shared by both collection modes.
Earlier participant runs remain explicitly operator-confirmed; do not pool
those timings with future automatic runs without addressing the protocol change.

## What is implemented

One server-owned cycle, independent of which of the three safety controllers is
assigned. Browser refresh does not restart or advance the cycle.
The current source runner is `automatic-panel-v6-stream-capture`: the server supplies the seven-stage
instruction and the dashboard shows a button only when confirmation is needed.
It no longer presents the old ten-step manual sequence as the automatic workflow.

1. Press **Start trial — suction turns on** with its assigned controller/event
   and server-generated trial files. After verifying the robot is stationary at the low
   pose, suction is off initially and the operator is clear, this single action
   starts recording and enables loading suction. There is no separate suction
   confirmation. Starting the service alone still never activates the gripper.
2. The backend automatically journals trial start using its local clock and saves
   streamed data. This does not claim hardware synchronization. A failed suction start
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
7. At the verified low pose, the panel rests on the established rigid gripper
   support. After two stationary seconds at that pose, release once and save.
   There is no unattended repeat loop.

Only start and task-complete confirmation are routine dashboard actions for an automatic trial.
The safety comparison still exercises controller response during motion.

## Short spoken script for the rehearsal

Explain before starting: “The suction will already be on when you place the
panel. Once the grip is confirmed, let go and step back to the start marker.
The robot will lift automatically. Stay there until we invite you to approach.
After task completion is confirmed, step back again; it will lower automatically.
At the bottom it waits two stationary seconds on the rigid support, then releases
suction. Only perform the agreed movement when
we give its cue. You can ask us to stop at any time.”

During the run, use the current dashboard instruction. Do not add another grip,
lift or lower command. “Task complete” is an actual observation, not a timer.
The arrival instruction is withheld until stationary telemetry is confirmed.
A pending lift/lower command is not described as proof of physical motion.

## Run software checks without hardware

From the repository root:

```sh
.venv/bin/python -m pytest tests/test_automatic_trials.py tests/test_dashboard_server.py
```

Tests use fake hardware only. They cover the complete sequence, independent
clearance and seal dwells, one-sided grip loss, invalid distance, stale readings,
failed controller output, timeouts, cancellation, supported-only release,
watchdog setup, target-pose checks, remote abort authentication, and API bypasses.

## Enable an automatic trial

Only after the team has set up the physical safeguards, known payload/centre of
gravity, supported loading/release positions and marked participant route:

```sh
python scripts/dashboard_server.py --share --enable-research-speed-output --enable-automatic-trials
```

Open **Participant study** for a P-code study run or **Qualification** for a
Q-code rehearsal. Both use the same automatic engine. Their collection modes
stay separate in samples, events and manifests, alongside `execution_mode=automatic`.
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

Every automatic run also records an `automation_task_contract` event and embeds
the contract in its saved manifest. It contains the protocol version, copied
taught joint poses, nominal task speed, vacuum setting, sequencing thresholds
and sequence, with a SHA-256 fingerprint. Controller and scenario identities are
separate experimental metadata, not inputs that alter this task contract. Compare
the task fingerprints across trials; do not silently pool different task setups.
If a taught pose or a captured setting changes during a run, the runner latches a
fault rather than adapting its task to make the attempt succeed.

Automatic capture grading checks completion, recording quality and the assigned
event-window labels, not model accuracy or safety. Missing/aborted manifests fail
completion. Native MVN/Motive files and video are optional external sources, not
prerequisites for stream capture. The manifest explicitly records that the backend
does not create those formats or record a camera. Existing references remain metadata.

Physical verification applies to both modes: witness the full cycle on the actual setup
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
- v3 adds the seven-stage server-owned instructions, frozen task contract,
  cross-condition task-sequence tests and verified-stationary arrival prompts.
  Full suite: 165 passed, including 42 automatic-trial cases. Lint/build passed.
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
