# Participant measurement and data-retention plan

**Frozen protocol candidate:** 2026-09-02
**Applies to:** final participant study on the UR10 ceiling-panel surrogate cell
**Status:** this document defines the measurement contract, but collection remains blocked until every collection-stage gate in `configs/research_readiness.yaml` has evidence.

## 1. Research question and unit of inference

> During one fixed, approved panel-handling task, does the predictive SSM policy reduce unnecessary robot interruption relative to fixed-zone and reactive-SSM references, without worsening response to a predefined rapid intrusion?

The study is a **within-participant controller comparison**. The participant is the independent unit for controller-effect estimates; the predefined intrusion is the unit for response-event estimates. Frames are repeated observations within trials and must not be treated as independent participants.

This study does not claim universal hazard, fall or trip detection. A rapid intrusion is an operational test event: an experimenter-cued, ethics-approved movement of the tracked participant proxy toward the validated protected volume. Task phase (`approaching`, `working`, `retreating`) and hazard exposure are separate variables.

## 2. Final participant protocol

Each participant completes three blinded blocks. They see only **A, B and C**. The operator uses the preassigned counterbalanced mapping to run each controller once:

- fixed zone;
- reactive SSM (simplified dynamic separation envelope); and
- predictive SSM (the same envelope plus the frozen phase/horizon context).

Each block has three trials, for nine trials per participant:

1. one clean trial with no inserted event;
2. one distractor trial with a predefined non-intrusion movement; and
3. one approved rapid-intrusion trial.

The inserted event window occurs during the same robot lift in every trial. The
participant begins at the verified start marker; the second deliberate operator
confirmation starts the lift and synchronized event cue together. In a rapid-
intrusion trial the participant performs only the approved brief closing movement
and immediately retreats. In a distractor trial the approved non-intrusion movement
occurs during the same lift. In a clean trial the participant remains at the marker.
No event is inserted while the robot is already stationary.

Rotate the three event positions within blocks and the controller order across participants. Do not insert both events in every trial. Keep robot path, task instructions, panel, cue wording, operator position and stopping policy identical except for the assigned controller. No model, threshold, geometry, event-definition or analysis change is permitted after the first reported participant unless a new study release is declared and the affected data are excluded under the frozen rule.

## 3. Outcome hierarchy

### Primary outcomes

The primary comparison is not questionnaire accuracy and not HMM frame accuracy.

1. **Intrusion response success:** proportion of predefined rapid-intrusion events that produce the required command before the validated boundary would be crossed.
2. **Protective-distance margin:** minimum of `d_validated(t) - S_required(t)` during each scored window, plus duration below zero. `d_validated` must use the validated protected robot/tool/panel geometry and the stated uncertainty bound, not head-to-TCP distance alone.
3. **End-to-end response time:** cue and participant movement onset are descriptive anchors; the safety chain is movement/boundary evidence → controller command → robot deceleration onset → verified zero motion.
4. **False interruption burden:** false stops per safe minute and total stop/slowdown duration in clean and distractor windows.
5. **Task time:** trial duration from the frozen task-start event to the frozen task-complete event.

### Secondary outcomes

- anticipation lead time relative to actual boundary crossing;
- minimum validated separation;
- time-integrated speed deficit relative to the trial's nominal command;
- human idle time, robot idle time, concurrent activity and functional delay;
- task success, errors and rework;
- tracking-valid proportion, stale/occluded duration and calibration/extrinsic residual;
- participant-reported perceived safety, trust, workload and unnecessary stopping.

### Exploratory behavioural outcomes

Do not count “looks at the robot” over the whole trial. The task itself encourages continuous observation, so a whole-trial count will ceiling and confound task demand with trust.

Use a **head-directed monitoring proxy** only inside a frozen autonomous-motion window:

- proportion of the window with the head directed toward the robot;
- off-to-on monitoring revisits per window;
- latency of the first head turn after robot motion or a speed change; and
- longest continuous off-robot interval.

These are not eye gaze. Derive them from the Xsens head quaternion or a validated OptiTrack head rigid-body orientation after a facing-direction calibration. Validate a predeclared subset against consented video with a second coder. Report agreement and missing/ambiguous intervals. A high monitoring proportion can mean vigilance, fear, task necessity or low trust; a low value can mean trust or dangerous complacency. Interpretation therefore requires task performance and questionnaire convergence.

## 4. Required synchronized data package for every trial

Every trial, including aborted trials, receives one immutable `participant_id + dashboard_trial_id` join key and one row in the Google Sheet `Trial log`. Preserve:

1. dashboard schema-v3 JSONL with all received Xsens segment positions and quaternions, raw OptiTrack rigid-body poses and quality, phase/event labels, classifier posterior, freshness flags, controller output and frozen artifact/config digests;
2. the native MVN recording from the Windows laptop;
3. the native Motive/OptiTrack take with the rigid-body definitions and quality indicators;
4. high-rate robot telemetry containing timestamped TCP/joint pose and speed, runtime/safety state, commanded speed fraction, stop/slowdown requests and actual motion response;
5. consented video that shows the participant, robot/panel and a visible or audible shared sync marker;
6. a compact event journal containing both monotonic and UTC timestamps for trial start/end, task cues, movement onset, distractor/intrusion onset, boundary crossing, controller command, deceleration onset, zero motion, task completion, abort and incident; and
7. the block and end questionnaires joined only by participant ID and blinded block label.

The sheet stores filenames and completeness checks, not hand-entered copies of robot metrics. Raw metrics are calculated reproducibly from the preserved files.

## 5. Synchronisation and calibration

At the start of each participant and after any restart, create one obvious shared sync event visible in Xsens, OptiTrack, robot telemetry and video. Record its timestamp in the trial manifest and verify alignment before proceeding.

Calibrate:

- Xsens body model and facing direction;
- OptiTrack rigid-body identity and world frame;
- the robot-to-tracking extrinsic transform;
- the participant proxy or occupied-volume rule; and
- the protected robot, tool, panel and swept-volume geometry.

Re-check calibration residual and tracking freshness before each block. A stale stream, swapped rigid body, incomplete 23-segment Xsens frame, missing robot telemetry, absent native recording or failed sync makes the trial incomplete; use the frozen exclusion/repeat rule before the participant leaves.

## 6. Frozen coding and analysis rules

- Predeclare exact event-window start/end rules and thresholds before collection.
- Summarise each outcome within trial, then within controller condition for each participant.
- Report paired participant-level differences with confidence intervals and effect sizes.
- With a small sample, use a Friedman omnibus comparison across the three conditions, followed only when justified by paired Wilcoxon signed-rank or exact paired permutation comparisons with Holm correction.
- Report event counts and binomial uncertainty for response success; do not turn thousands of adjacent frames into an artificial sample size.
- Keep the HMM's participant-held-out balanced accuracy as a development diagnostic. It is not a participant safety outcome.
- Preserve all failed, aborted and excluded trials. Never delete or overwrite them; record the predeclared reason.

## 7. Before-participant dry run and no-go rule

Run one complete nine-trial mock participant using the final counterbalancing row and event schedule. Before the mock operator removes the suit, confirm that all nine `Trial log` rows have every required filename and a `Y` for sync, Xsens, Motive, robot telemetry, event timestamps and trial completeness. Recompute at least one example of every primary and secondary metric from raw files, and manually validate at least one head-direction window against video.

Do not begin reported moving-participant collection if any collection-stage gate is red, any Google Form is inaccessible from a participant device, the dashboard cannot record the assigned block/controller/event metadata, or the robot/controller path cannot produce the required high-rate telemetry and event timestamps. A stationary-arm sensing session may proceed only if the approved protocol and lab supervisor allow it, and it must not be reported as live adaptive safety performance.

## 8. Evidence basis

The separation and response-time framing follows the scopes of [ISO/TS 15066](https://www.iso.org/standard/62996.html) and NIST's implementation work on [speed and separation monitoring](https://www.nist.gov/publications/implementing-speed-and-separation-monitoring-collaborative-robot-workcells). The efficiency measures follow Hoffman and Breazeal's HRC fluency metrics: [human idle, robot idle, concurrent activity and functional delay](https://hrc2.io/assets/pdfs/papers/HoffmanTHMS19.pdf). Behaviour and perception are intentionally triangulated because objective and subjective trust markers can diverge; gaze-like monitoring measures are context-sensitive and cannot be interpreted as trust by themselves ([Trust Measurement Toolkit](https://doi.org/10.1145/3530874), [HRC gaze study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10382291/)).
