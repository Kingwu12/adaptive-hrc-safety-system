# Team guide: final participant experiment

**Project:** Adaptive Human-Robot Collaboration Safety Through Motion-State Recognition and Predictive Speed-and-Separation Monitoring  
**Protocol version:** candidate v1, 9 September 2026  
**Audience:** the full FYP team, lab supervisor and anyone operating the participant session  
**Authority:** this guide explains the study. The machine-readable contract remains `configs/analysis_plan.yaml`, and collection may begin only when `configs/research_readiness.yaml` passes the collection stage.

## The experiment in one minute

We are testing one question:

> During the same panel-handling task, does the predictive safety controller reduce unnecessary robot interruption compared with fixed-zone and reactive speed-and-separation monitoring, without making the response to a controlled rapid-closing movement worse?

Each participant completes **nine trials**:

- three trials under blinded controller **A**;
- three trials under blinded controller **B**; and
- three trials under blinded controller **C**.

A, B and C map to the three controllers in a counterbalanced order. Within every controller block, the participant completes one **baseline**, one **safe-motion challenge**, and one **controlled closing challenge**. Therefore, every participant experiences all nine controller-scenario combinations exactly once.

This is **not nine questionnaires**. The participant completes five form handoffs in total:

1. one intake form before fitting the suit;
2. one feedback form after Block A;
3. one feedback form after Block B;
4. one feedback form after Block C; and
5. one final comparison survey and debrief.

There is no questionnaire between the three trials inside a block.

## What is being compared

### Controller 1: fixed zone

The robot uses fixed distance zones. Its action depends on the participant's current position relative to those zones. It does not use the HMM.

This is the simple reference condition: conservative and understandable, but potentially prone to unnecessary slowing or stopping.

### Controller 2: reactive SSM

SSM means **speed-and-separation monitoring**. This controller uses the current measured separation and current closing speed to calculate a dynamic protective envelope. It does not use the HMM.

This tests how much improvement comes from reacting to current motion rather than relying only on fixed zones.

### Controller 3: predictive SSM

This controller uses the same reactive envelope plus the frozen task-phase model and forward prediction. The model estimates whether the participant is approaching, working or retreating and helps the controller anticipate likely near-future motion.

The learned model is not allowed to make the robot less cautious than the deterministic envelope. It may add caution, but it may not command above the envelope's bound. The independent safety-rated robot protection remains the actual safety authority.

### What the participant knows

The participant sees only **A, B and C**, not the controller names or the hypothesis. They receive the same task instructions in every block. They are told and rehearsed on the approved movements needed for the scenarios, because those actions must be controlled and safe.

This is participant-blinded, not double-blinded: the operator may need to know the assigned controller and scenario to run the equipment correctly.

## The three scenarios

The dashboard and data files currently use `clean`, `distractor` and `rapid intrusion`. For team and participant-facing explanation, use the clearer terms below.

### Scenario 1: baseline

**Internal label:** `clean`

The participant returns to the marked start position after placing the panel. During the robot lift and scored event window, they remain at that position and perform no inserted movement.

This is the easy safe case. It measures whether the controller slows or stops when there is no extra movement toward the robot.

### Scenario 2: safe-motion challenge

**Internal label:** `distractor`

At the synchronized cue during the lift, the participant performs one predefined movement that does not enter or rapidly close on the protected volume.

The final movement must be one supervisor-approved action with a marked start, direction, duration and endpoint. It should resemble the controlled closing challenge in speed and duration as closely as practical while differing mainly in closing direction. A brisk lateral or tangential motion is the intended principle; it is not permission to improvise the exact action.

This is the difficult safe case. It tests whether the controller distinguishes **movement** from **dangerous closing movement**. A robot that stops whenever a person moves may appear safe in the challenge trial but will fail here through false interruptions.

### Scenario 3: controlled closing challenge

**Internal label:** `rapid intrusion`

At the same synchronized cue during the lift, the participant performs one brief, rehearsed movement along the approved marked direction toward the validated protected volume, then immediately retreats before the hard safe endpoint.

This is not a fall, trip, stumble, surprise lunge or improvised hazard. It is a controlled positive challenge with a measurable onset and path. Its purpose is to compare controller response, protective-distance margin and stopping behaviour under rapid closing motion.

The following values must be written into the final signed-off physical script before Q01 and must not be guessed from this guide:

- marked starting position;
- permitted direction and path;
- cue wording;
- permitted speed or execution instruction;
- maximum endpoint and no-cross boundary;
- retreat instruction;
- operator and E-stop positions; and
- abort condition.

If the action cannot be made repeatable and safely approved, it must not be performed by a participant. A tracked proxy or a different approved protocol would be a different study release.

## Why these three scenarios are necessary

The three scenarios separate three behaviours that would otherwise look identical in a weak experiment:

- The **baseline** reveals needless reactions when nothing happens.
- The **safe-motion challenge** reveals false positives when noticeable but safe movement happens.
- The **controlled closing challenge** reveals whether the controller responds appropriately to the defined rapid-closing event.

Testing only baseline trials would reward a controller that never stops. Testing only closing challenges would reward a controller that always stops. The safe-motion challenge is what tests useful selectivity.

## Why the same controller is used for three trials

Each block holds the controller constant while the scenario changes:

```text
Block A: controller A + baseline + safe-motion + controlled-closing
Block B: controller B + baseline + safe-motion + controlled-closing
Block C: controller C + baseline + safe-motion + controlled-closing
```

The participant is not repeating the same trial three times. They are testing the same controller in three meaningfully different situations.

The block structure also allows one questionnaire after all three situations under that controller. Controller order changes across participants, and scenario order changes within blocks, so the result is less likely to be explained by learning, fatigue or always seeing the closing challenge last.

This is a minimal **within-participant factorial design**: every participant acts as their own comparison across three controllers and three scenarios. One trial in each cell is efficient but provides limited trial-level repeatability. We must report that limitation honestly; nine trials do not support claims about every possible person, task or hazard.

## The complete participant workflow

### Before the participant arrives

1. Use only the frozen study release, final robot program, controller configuration and model artifact.
2. Confirm the approved protocol and participant-facing forms match what will happen physically.
3. Check the robot safety-rated protection, E-stop, gripper, panel support and recovery procedure with the lab supervisor.
4. Confirm Xsens, OptiTrack, robot telemetry, video and local storage are available.
5. Open the participant dashboard and confirm the public form routes work on a signed-out phone.
6. Prepare the next unused anonymous participant code. Never reuse a pilot or participant code.

### Verbatim participant opening script

The study lead reads the following after the approved consent process and before fitting the suit. Do not paraphrase the study structure differently for different participants.

> Thank you for taking part. Today you will complete the same panel-handling task nine times: three trials in each of three blocks called A, B and C. The letters represent different robot behaviours, but we will not tell you which is which until the study is finished.
>
> In every trial, you will carry the panel to the robot, align it on the suction gripper, let go and return to the marked start position. The robot will then lift the panel. During that lift, you will either remain at the marker, perform the safe movement we have rehearsed, or perform the controlled closing movement we have rehearsed and immediately retreat. Only perform a movement when the experimenter gives the cue. Do not improvise, run, fall or try to surprise the system.
>
> After the lift, you will approach the raised panel, complete the same task, retreat to the marker and wait while the robot lowers the panel. Follow the operator's instruction before approaching or touching the panel at any point.
>
> You will answer a short form before the suit goes on, after each three-trial block, and once at the end. There is no form after every individual trial. We are recording synchronized motion-capture, robot and video data under your anonymous participant code.
>
> You can pause or stop at any time without giving a reason. If you feel uncomfortable, unsure or notice anything unexpected, say “STOP” immediately and remain where you are unless the safety operator directs you to retreat. Do you have any questions before we demonstrate and rehearse the two approved movements?

After reading the script, demonstrate the final supervisor-approved safe-motion and controlled-closing actions away from active robot motion. The participant rehearses each action only under the approved procedure. Do not begin the study if they cannot perform both actions comfortably and repeatably.

### Verbatim pre-trial scenario cues

Use only the cue matching the dashboard-assigned scenario. The words in square brackets must be replaced by the exact terms in the signed-off physical movement script before Q01.

- **Baseline:** “The robot lift will start after the second confirmation. Remain at the start marker until I tell you to approach the raised panel. There will be no movement cue in this trial.”
- **Safe-motion challenge:** “When the lift starts, wait for me to say NOW. On NOW, perform the rehearsed [safe-motion action] once, return to the start marker and wait.”
- **Controlled closing challenge:** “When the lift starts, wait for me to say NOW. On NOW, perform the rehearsed [controlled-closing action] once, stop at the approved endpoint, immediately retreat to the start marker and wait.”

Immediately before each block, say: “This is Block [A, B or C]. It contains three trials under the same robot behaviour. The movement order is assigned by the dashboard. Perform only the action I cue, once.”

### Intake and instrumentation

1. Explain the approved study, answer questions and complete consent before collecting data.
2. Create the anonymous participant code in the dashboard.
3. Show the intake QR code. Confirm the prefilled anonymous ID and wait for the response to reach the Sheet.
4. Fit and calibrate the Xsens suit.
5. Confirm the OptiTrack rigid-body identity and tracking volume.
6. Confirm the robot-to-tracking transform and protected geometry.
7. Create the shared synchronization event visible in Xsens, Motive, robot telemetry and video.

### Before every trial

1. Use the dashboard's assigned block, controller and scenario. Do not manually choose a preferred order.
2. Confirm fresh 23-segment Xsens data, fresh OptiTrack data, robot readiness and recent calibration.
3. Start native MVN, Motive and video recording with the filenames shown by the dashboard.
4. Confirm the three recordings are visibly running before starting the dashboard trial.
5. Put the robot at the verified low pose with suction off and confirm the cell is clear.

### The physical trial

1. The participant starts on the marked position holding the lightweight panel.
2. They approach the low gripper normally.
3. They align the panel against both suction cups while the operator arms, grips and verifies suction.
4. The participant lets go and retreats fully to the marked start position.
5. When tracking confirms the cell is clear, the operator's deliberate second confirmation starts the robot lift and the scored event window together.
6. During that lift:
   - baseline: no event cue; the participant remains at the marker;
   - safe-motion: give the synchronized cue for the approved non-closing action; or
   - controlled-closing: give the synchronized cue for the approved brief closing action and immediate retreat.
7. After the robot reaches the raised position, the participant approaches and performs the same panel task normally.
8. No second scenario event is inserted during the raised-panel work.
9. The participant retreats to the start marker.
10. When the cell is clear, the operator lowers the robot. Suction remains on while the panel is overhead.
11. At the verified low stationary pose, the participant supports the panel and the operator releases suction.
12. Stop and save all recordings. Verify the files exist and complete the trial-log row before continuing.

Any operator mistake, tracking failure, robot fault or participant concern triggers an abort. Preserve the attempt and its reason; never overwrite it or silently relabel it as successful.

### Between blocks and at the end

After each three-trial block, show the corresponding blinded block QR and confirm that its response reaches the Sheet. Do not reveal the controller mapping.

After all nine accepted trials, show the final survey QR, complete the approved debrief, record incidents, duplicate the raw data and check that every file joins to the correct anonymous participant and trial ID.

## What is recorded

Every attempted trial must have one immutable participant-and-trial join key across:

- dashboard schema-v3 JSONL;
- all 23 Xsens segment positions and orientations received by the dashboard;
- native MVN recording;
- native Motive take and tracking-quality indicators;
- high-rate robot pose, speed, state, command and response telemetry;
- controller inputs, outputs, model/config digests and event timestamps;
- consented synchronized video;
- trial-log completeness and exclusion fields; and
- blinded questionnaire responses.

Xsens and OptiTrack are not interchangeable. Xsens provides body-segment motion and orientation; OptiTrack provides external position/reference evidence. The robot log provides what the robot was commanded to do and what it actually did. Synchronization is what makes the three streams scientifically comparable.

## What counts as the result

The primary result is not the HMM's frame-by-frame accuracy and not whether participants say they liked the system.

The primary controller outcomes are:

1. **Closing-challenge response success:** did the required command occur before the validated boundary would be crossed?
2. **Protective-distance margin:** how close did validated separation come to the required separation, and for how long was the margin below zero?
3. **End-to-end response time:** how long from measured event evidence to controller command, robot deceleration and verified zero motion?
4. **False-interruption burden:** how often and for how long did the robot unnecessarily slow or stop during baseline and safe-motion periods?
5. **Task time:** how long did the fixed task take under each controller?

Secondary results include robot/human idle time, concurrent activity, errors, rework, tracking quality, perceived safety, trust, workload and perceived unnecessary stopping.

Head direction may be analysed only as an exploratory **head-directed monitoring proxy** during the predefined autonomous-motion window. It is not eye gaze and cannot, by itself, prove trust or fear.

## Analysis logic

1. Calculate outcomes from synchronized raw data for each trial.
2. Aggregate trials within controller for each participant.
3. Compare the three controllers using paired participant-level statistics.
4. Examine scenario type and controller-by-scenario patterns without treating adjacent sensor frames as independent people.
5. Report effect sizes, uncertainty, participant counts, event counts, exclusions and protocol deviations.
6. Keep participant outcomes separate from model-development accuracy.

The important comparison is whether predictive SSM improves efficiency in safe situations **without sacrificing the response to the controlled closing challenge**.

## Repeat, exclusion and freeze rules

A trial is repeated only for a predeclared reason such as missing native MVN recording, incomplete Xsens stream, stale or swapped OptiTrack body, missing robot telemetry, failed synchronization marker, equipment/operator abort or protocol deviation.

The first complete valid attempt for an assigned slot is primary. Every failed, aborted or repeated attempt remains stored with its reason.

After the first reported participant, do not retrain the HMM, tune thresholds, alter geometry, change scenario definitions, change the analysis or modify controller/dashboard code. A necessary change creates a new study release and the affected data must be separated.

Participant data is evaluation data. It is not extra training data.

## What this study can and cannot claim

If completed correctly, the study can compare the three frozen controllers for this approved panel task, cell, equipment, participant sample and controlled event definition.

It cannot establish:

- universal hazard, fall or trip detection;
- certified robot safety performance;
- safe operation without the independent robot safety chain;
- general performance for every person, workplace or task;
- eye gaze, trust or fear from head direction alone; or
- population-level model generalisation from repeated runs by the same few operators.

## Team responsibilities

Before each session, explicitly assign these responsibilities. One person may hold more than one role only if the supervisor agrees that the workload remains safe.

### Study lead

- owns consent, participant ID, script consistency, counterbalancing and questionnaires;
- confirms the participant understands the task and approved scenario movements;
- records incidents and deviations without coaching the desired result.

### Robot and safety operator

- owns robot state, panel/gripper checks, two-step motion confirmations, E-stop access and abort/recovery;
- never starts motion until the cell-clear condition is visibly satisfied;
- treats the independent safety chain, not the HMM or dashboard, as the protective authority.

### Data operator

- owns MVN, Motive, video, dashboard and robot-recording readiness;
- checks filenames, synchronization, tracking freshness and post-trial file completeness;
- prevents moving on to the next trial while evidence is missing.

### Participant

- follows the approved task and scenario script at a comfortable, rehearsed pace;
- may stop or withdraw at any time;
- is never asked to improvise a fall, trip or hazardous movement.

## Final no-go rule

Do not start a reported moving-participant comparison unless the collection readiness command passes and the physical witnesses are present. In particular, no approved and frozen movement script, no validated protected geometry, no measured stopping-time and uncertainty bound, no safety-rated output, no synchronized objective logging, no accessible forms or no supervisor-witnessed recovery path means **no reported moving-participant run**.

A stationary-arm sensing session may proceed only when the approved protocol and supervisor permit it, and it must be described as a different experiment.

## Canonical companion files

- `configs/analysis_plan.yaml`: frozen design, outcomes and statistics contract.
- `configs/research_readiness.yaml`: evidence gates that authorize each research stage.
- `docs/participant-measurement-plan.md`: detailed measurement and retention contract.
- `docs/wednesday-participant-readiness-checklist.md`: lab-day checklist and qualification acceptance tests.
- `docs/prestudy-qualification-runbook.md`: ten-run Q-code rehearsal and freeze procedure.
- `docs/ethics-reconciliation-delta.md`: unresolved differences between approved materials and the implemented study.

When this guide and a machine-readable contract disagree, stop. Reconcile the documents and issue one new version before collecting data; do not choose whichever instruction is more convenient during the session.
