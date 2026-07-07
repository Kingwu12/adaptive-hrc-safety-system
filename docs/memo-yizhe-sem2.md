# Methodology Memo — Sem-2 Redesign

**To:** Yizhe (Will) Wang (supervisor)
**From:** Zenan Wu, Luke Siniakov, Michael Magila
**Re:** Sem-2 methodology changes + the v2 task + ethics timeline
**Date:** 2026-07-06

One page on what we are changing for semester 2 and why, plus the one thing that is
time-critical (ethics). Full detail in `docs/design/sem2-redesign.md`.

## 0. The task changed — one repeating "Panel Cycle" (this is the biggest change)

**What changed from the prior scenario.** The old task was a generic "approach a work face,
fasten at a few stances, retreat" loop. It never contained a phase where a fixed safety
distance was genuinely impossible to satisfy, so static and adaptive only differed by
*degree*. The v2 task is one repeating **Panel Cycle** of ceiling-panel installation with a
phase that static logic essentially *cannot do at all*.

**The cycle in one paragraph.** The robot is a lifting jack with a releasable
gripper (nothing is ever bolted to the robot); the participant is loader, aligner, and
bolter. Five phases repeat: **P1 LOAD** (arm parked at waist, human slides the panel on);
**P2 TRANSIT** (robot lifts and aligns the panel while the human tends the shared space —
concurrent motion); **P3 HAND-GUIDE** (robot holds the panel *compliantly* and the human
nudges it a few mm *by hand* — real contact, ISO/TS 15066 hand-guiding mode); **P4 BOLT**
(human bolts the panel into the *ceiling* while the robot holds dead still); **P5 RELEASE**
(robot releases and lowers as the human finishes and steps down — concurrent motion again).

**Why the measurement windows are the transitions and the hand-guiding, NOT the hold.** We
only compare static vs adaptive where they *can* differ. That is P2 and P5 (concurrent
motion — adaptive can keep working for a person who is not actually closing) and P3
(hand-guiding — adaptive permits the contact by recognising the *certified compliant-hold
mode*; static protective-stops and the task is infeasible). We **explicitly do not** measure
P4: there the robot is meant to be dead still, so static and adaptive are identical —
comparing "how well each holds still" measures nothing. Saying this out loud is deliberate:
mistaking the P4 hold for a measurement window was the confusion this redesign resolved.

**Metrics, per phase.** cycle time, protective-stop count, minimum separation distance, and
human idle time — reported for the measurement windows (P2/P3/P5) separately from the P4
hold, plus a post-condition fluency/trust questionnaire. **Hypothesis:** adaptive matches
static on safety (zero separation violations) while improving cycle time, stops, and idle
time, with P3 **near-binary** — feasible under adaptive, effectively infeasible under static.

## 1. Metric redefinition (resolves a contradiction in the sem-1 Table I)

Our sem-1 "unnecessary interruption" metric counted *any* slowdown while the operator
was working as a penalty — but our own control table **prescribes** a slowdown for a
working operator in the warning band. We were penalising the controller for doing what
we designed it to do. We are freezing a new **primary** outcome: **interruption burden**
= the time-integrated speed deficit over ground-truth-*safe* periods (excluding hazard
windows and red-zone occupancy), scored **identically** for every controller. Because
everyone is charged the same way for the same true situation, the comparison now isolates
**contextual reasoning**, not rule-table compliance. Old count metrics stay as secondary.
We froze this definition *before* looking at outcomes to keep it honest.

## 2. Safety-envelope architecture (the key conceptual shift)

Sem-1 let the learned model reason its way *up* to full speed — putting a non-certified
model on the safety-critical path. Sem-2 inverts this: a certified **speed-and-separation
envelope** (ISO/TS 15066, but using the *measured* approach speed) is a hard **floor**,
and the learned Recognise–Predict–Adapt layer sits on top and can only **add caution,
never remove it** (`final = min(envelope, model)`). A recognition error now makes the
robot too slow (annoying), never too fast (dangerous). This is the standard
runtime-assurance / shielding pattern and it makes the safety argument defensible without
certifying the learned model. The red-zone hard stop remains absolute on top.

## 3. Three-rung comparison + replay ablation

We now compare three controllers over the identical trace: **fixed-zone** (deployed
practice), **dynamic-SSM** (the speed-aware envelope alone — the *standards* rung), and
the **full** system. An offline **replay** tool runs any controller over a logged trace,
so ablations (full − prediction, full − state layer) are free. This lets us attribute
each gain to its source: speed-awareness vs. state-awareness vs. prediction.

## 4. Distractor protocol (specificity, not just sensitivity)

We are adding **cued distractors** — a fast lateral dart and a fast retreat, both
ground-truth *non-hazard*. They test **specificity**: a controller that stops for *any*
fast motion would pass a slip-only test yet be useless in practice. We will report hazard
**sensitivity and specificity** together.

## 5. URSim-first

We validate the full command path in **URSim** (speed slider + protective stop) before
any hardware, and before pilot data collection. Zone geometry and stopping time `T` are
re-measured on the real setup during pilot calibration — the config values are cold-start
placeholders.

## 6. ⚠️ Ethics — time-critical

This is the item that gates everything and needs your steer **now**. MUHREC review is
realistically **4–8 weeks**. Our protocol needs coverage for all of:

- **Cued slips** — the experimenter cues a near-approach to the robot column at
  randomised times (the cue timestamp is our hazard-onset ground truth).
- **Cued distractors** — fast but safe motions (new for sem-2).
- **Video recording** — needed for offline labelling of operator state.
- **Open-dataset consent** — we want to publish an anonymised motion dataset, which
  needs an explicit consent item.

Mitigations we are proposing: a **lightweight surrogate panel** (not a real ceiling
panel), **e-stop** within reach, continuous **supervision**, and the robot held in
**stationary hold** during early pilots so the induced slip approaches a *stationary*
arm. The red-zone protective stop is active in **both** conditions, so neither condition
is less safe.

**Ask:** please confirm (a) the metric redefinition (option a) is acceptable, and (b)
whether we should submit the ethics application against the **full** protocol now
(slips + distractors + video + open-dataset consent) to avoid a second review cycle. A
draft skeleton is in `docs/ethics/skeleton.md`.
