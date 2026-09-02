# Research-readiness audit — 2026-09-02

## Decision

The repository is suitable for continued engineering and controlled pilot work, but it
is **not yet ready for a reported moving-participant controller comparison**. Run
`python scripts/research_readiness.py` for the evidence gates. A red gate is not a request
for more model training; it is a missing part of the experimental safety case or validity.

## 1. Research question, derived from first principles

The defensible question is:

> During a fixed, approved ceiling-panel surrogate task, does an adaptive command policy
> reduce unnecessary robot interruption relative to fixed-zone and simplified dynamic-
> envelope reference policies, without worsening response to predefined rapid intrusions?

This is not a study of “all hazards.” A hazard source, an initiating event, a hazardous
situation and harm are different things. For example, a trip is an initiating event; a
person entering the moving robot's reachable volume is the hazardous situation; impact or
crushing is the possible harm. The system must control the hazardous situation even when
it cannot name the initiating event.

Task phase and risk are also orthogonal. A person may be `working` while slipping, or
`retreating` while an arm or dropped panel creates danger. Therefore the four-state HMM's
legacy `hazard` label is an experimental activity/event label, not a universal fourth task
state and not the safety truth.

## 2. What each layer can honestly claim

| Layer | Current input | Defensible role | It cannot establish |
|---|---|---|---|
| OptiTrack geometry | One tracked head rigid body and live TCP | Head-proxy distance and closing kinematics | Full body or reaching-limb clearance |
| Xsens path | Historical pilot files: pelvis XYZ only. Schema v2 onward: all received segment positions/quaternions, while the current model still excludes them | Concurrent wearable trace; future posture/event-feature research after validation | Existing-pilot full-body evidence, validated fall recognition or safety-rated fusion |
| GMM-HMM | `d`, `v_proj`, speed, `a_proj` | Development activity classifier and optional conservative slowdown context | General hazard detection or safety certification |
| Kinematic horizon | Head-proxy distance, closing speed and acceleration | Anticipation of a defined rapid boundary intrusion | Intent, loss of balance, or arbitrary hazards |
| Zone/envelope code | Simplified `K*T+C+Sa` geometry | Reproducible deterministic command bound for comparison | A complete validated protective-separation calculation |
| Robot output | RTDE slider plus Dashboard pause | Simulation/bring-up stop request | Safety-rated protective stop |

The learned layer is now gated so a sticky `hazard` posterior cannot by itself create a
pre-emptive stop while the tracked point is stationary or retreating. The fixed red-zone
software invariant remains independent of the learned label.

## 3. Hazard analysis for the whole robot system

The study needs multiple independent control channels, not one classifier:

| Hazardous situation | Examples of initiating event | Detection/control channel |
|---|---|---|
| Person approaches moving robot/tool/panel | deliberate approach, stumble, trip, distraction | validated protected geometry, separation monitoring, safety-rated stop |
| Limb enters swept volume while head stays clear | reaching, fastening, hand contact | task design, whole occupied-volume model, validated collaborative mode; head proxy alone is insufficient |
| Robot moves unexpectedly | program fault, wrong pose, communications error | robot safety functions, speed/pose limits, program validation, e-stop |
| Panel or tooling becomes unstable | vacuum loss, bad payload, incomplete fastening | independent vacuum/attachment interlocks and mechanical support |
| Tracking or calibration becomes invalid | stale packet, rigid-body swap, occlusion, transform error | freshness/identity checks, conservative uncertainty, fail-closed stop path |
| Intended contact becomes unsafe | incorrect hand-guiding mode, excessive force, pinch geometry | validated hand-guiding/PFL setup, force and speed limits, task-specific risk assessment |

Passing the motion classifier does not close any row by itself.

## 4. Model and training audit

The 32 accepted runs from three people are useful development data. They provide many
frames and repeated motions, but the independent human sample size for population
generalisation is three, not 32 and not 107,217 frames. More repetitions reduce noise for
those people; they do not create new body shapes, movement strategies or sensor placement.

That does **not** make next week's experiment impossible. It changes the claim:

- Valid now: performance on the enrolled operators and the defined task; within-person
  controller comparison; event-level response on predefined cued intrusions.
- Not valid now: performance on unseen people, arbitrary falls, all real-world hazards, or
  deployment outside this cell.

The corrected participant-held-out development estimate is approximately 0.670 accuracy,
0.490 legacy-hazard precision and 0.526 legacy-hazard recall. Decoding is now reset at
unlabelled gaps; this correction barely moves the score, so the weakness is substantive.
Frame accuracy remains a secondary diagnostic because adjacent 60 Hz frames are highly
correlated and long `working` intervals dominate it.

For the reported study, freeze the model, thresholds, exclusions and event definition
before collection. Do not retrain between participants or inspect final-test labels and
then retune. The primary statistical unit is the participant (for paired controller
effects) or the predefined event (for response), not an individual frame.

## 5. Frozen next-week protocol

1. Close every hardware/evidence gate in `configs/research_readiness.yaml` on the exact
   final robot, program, tool, panel, sensing layout and stop chain.
2. Use one operational event: an experimenter-cued, ethics-approved rapid movement of the
   tracked head proxy toward the validated protected volume during an SSM phase. Do not
   improvise real falls or trips.
3. Keep fixed-zone, dynamic-envelope and adaptive conditions on the same task and command
   path. Randomise or counterbalance order within participant.
4. Freeze the active model artifact and commit its digest before the first reported run.
   Today's three participants remain development/calibration participants unless the
   analysis plan explicitly defines a within-person study without unseen-person claims.
5. Log cue onset, movement onset, boundary crossing, command time, robot zero-motion time,
   tracking freshness, robot mode, controller version and exclusion reason.
6. Primary safety-response outcomes: event detection rate, false-stop episodes per safe
   minute, response latency, anticipation lead time, minimum validated separation and any
   violation. Primary efficiency outcomes: task time, stop/slowdown duration and human idle
   time. Report participant-level paired estimates and uncertainty, not frame-level
   pseudo-replication.
7. Keep synthetic traces for regression tests only. The paper now withholds its synthetic
   result tables by default.

## 6. Go/no-go rule

If reaction/stopping time, total sensing uncertainty, protected geometry, safety-rated
output, controller integration or approved-protocol reconciliation is not witnessed, do
not run a moving-participant SSM comparison. A stationary-arm data-collection session may
still be possible if it is within the approved protocol and the lab supervisor's risk
controls, but it is not evidence of live adaptive robot safety performance.

The standards framing follows the official scopes of
[ISO 12100](https://www.iso.org/standard/51528.html),
[ISO 10218-2:2025](https://www.iso.org/standard/73934.html), and
[ISO/TS 15066](https://www.iso.org/standard/62996.html). Standards define the risk-
assessment and collaborative-operation context; importing an equation or enum does not
certify this implementation.
