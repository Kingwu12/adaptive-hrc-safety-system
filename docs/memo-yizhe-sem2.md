# Methodology Memo — Sem-2 Redesign

**To:** Yizhe (Will) Wang (supervisor)
**From:** Zenan Wu, Luke Siniakov, Michael Magila
**Re:** Sem-2 methodology changes + ethics timeline
**Date:** 2026-07-06

One page on what we are changing for semester 2 and why, plus the one thing that is
time-critical (ethics). Full detail in `docs/design/sem2-redesign.md`.

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
