# Wednesday participant-readiness checklist

Use this on the final lab setup. A software test or a green dashboard does not replace the physical witnesses below.

## Ten-run qualification batch

Use the planned ten pre-study runs as system qualification, not extra training data:

- **Q01–Q09:** one complete mock participant: three blinded blocks × three trials, covering clean, distractor and approved rapid-intrusion once in each block. Use the final counterbalancing row, task wording, robot path, panel, operator position and forms.
- **Q10:** a controlled recovery rehearsal. While no participant is exposed to moving machinery, demonstrate the approved stop/abort path, preserve the aborted files, recover the rig, and show that the next trial receives a new ID rather than overwriting anything.

For every Q run, complete one row in the Google Sheet `Trial log` before removing the suit. All six evidence checks must be `Y`: sync marker, 23-segment Xsens, Motive validity, robot telemetry, event timestamps and trial completeness. Pair a unique dashboard JSONL, event JSONL, native MVN file, Motive take, robot trace and video filename.

In every completed Q run, the inserted window must coincide with the robot lift.
Clean means the mock operator stays at the start marker; distractor means only the
approved non-intrusion movement; rapid intrusion means only the approved brief
closing movement followed by immediate retreat. A stationary-robot event does not
qualify the controller comparison.

## One-time cell checks before Q01

- [ ] Disable any VPN route that captures the robot subnet. `route -n get 192.168.2.101` must resolve through the dedicated lab Ethernet interface, not `utun`; then confirm non-empty UR Dashboard status and a live RTDE TCP pose.
- [ ] Approved protocol, participant information, consent and video wording match the actual UR10, Xsens, OptiTrack, robot telemetry, panel task and rapid-intrusion event.
- [ ] Intake, per-block and end forms open on a signed-out participant device; one dummy submission reaches the correct response tabs.
- [ ] In the dashboard `Participant phone` panel, test all three form types on the actual participant phone and unlock their QR handoffs before the first participant arrives.
- [ ] Counterbalancing sheet assigns only A/B/C to the participant and maps each to one controller for the operator.
- [ ] Final model, controller, thresholds, geometry, config and code revision are frozen and their hashes are recorded.
- [ ] Xsens body/facing calibration, OptiTrack rigid-body IDs, robot-to-tracking extrinsics and protected tool/panel swept volume are validated.
- [ ] Measured sensing uncertainty and end-to-end stop time are incorporated into the required separation calculation.
- [ ] The robot safety-rated stop path, e-stop, speed/pose limits, gripper/panel support and recovery procedure are witnessed with the lab supervisor.
- [ ] Storage has room for all raw files plus a same-day duplicate; camera framing shows participant, robot/panel and sync marker.

## Rehearsal acceptance tests

- [ ] The dashboard cannot start without fresh 23-segment Xsens, fresh OptiTrack, recent calibration, a unique visible native MVN filename, a block, within-block trial, controller and planned event.
- [ ] Clean trials do not receive a hazard/distractor label; distractor and rapid-intrusion trials receive only their planned event.
- [ ] Every main JSONL row contains study metadata, full Xsens frame, raw OptiTrack rigid-body poses/orientations, model digest and live robot telemetry.
- [ ] Every companion event JSONL contains UTC and monotonic timestamps for start, step changes, action requests/completions and stop/abort.
- [ ] One shared sync event can be found in Xsens, Motive, robot telemetry and video, with an acceptable measured alignment error.
- [ ] One example of every primary outcome can be recomputed from raw files: intrusion response success, protective-distance margin, end-to-end response time, false interruptions and task time.
- [ ] One example of every secondary outcome can be recomputed: lead time, minimum separation, speed deficit, human/robot idle, concurrent activity, functional delay, errors/rework and tracking validity.
- [ ] One head-directed monitoring window is computed from orientation and checked against consented video. It is labelled as a head-direction proxy, not eye gaze or trust.
- [ ] Q10 proves aborts are retained, the arm/panel can be recovered safely and no filename or trial ID is reused.

## Participant-day loop

1. Assign the next unused ID; never reuse pilot IDs.
2. Confirm eligibility, consent and video permission before fitting sensors.
3. Calibrate and record the shared sync marker.
4. For each block, select A/B/C, its mapped controller and trials 1–3 with the frozen event order.
5. After each trial, stop all recordings and fill the `Trial log` row immediately. Do not give the participant a questionnaire between the three trials inside a block. Repeat only under the frozen rule while the participant is still present.
6. After trial 3 of each block, choose `Block A`, `Block B` or `Block C` in the dashboard phone panel, show its full-screen QR, and check that the blinded response row arrived.
7. At session end, show the dashboard end-survey QR, check that its row arrived, record incidents, duplicate raw files and verify nine complete trial rows.

## No-go

Do not start a reported moving-participant run while any collection-stage readiness gate is red. In particular: no verified safety-rated output, protected geometry, stop-time/uncertainty bound, controller integration, synchronized objective logging, accessible forms or approved protocol means **no moving-participant comparison**. Escalate to the supervisor; a stationary-arm sensing session is a different claim.
