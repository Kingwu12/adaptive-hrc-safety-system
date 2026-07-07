# Semester-2 Redesign — Adaptive HRC Safety System

Companion to the paper *"Comparing Static and Adaptive Safety Logic in Human-Robot
Ceiling Panel Installation"* (Wu, Siniakov, Magila, Monash 2026). This is the design
record for the five sem-2 changes. Each section states **what changed**, gives a
**plain-English WHY** you can defend in a viva, and points at the code and tests.

The thread running through all five: **make the safety argument something you can
certify, and make the scoreboard measure the thing you claim to improve.**

---

## The experimental task — one "Panel Cycle" (v2)

This section explains the v2 task in plain English. No robotics background is needed; the
ISO/TS 15066 terms are used precisely where they matter.

### Why this task exists

We want to compare two ways of keeping a person safe next to a moving robot:

- **Static** safety logic: one fixed safety distance, drawn for the worst case. Simple,
  certified, deployed everywhere today — but blunt. It slows or stops the robot for a
  person who is standing still or moving away, because it always assumes they might lunge.
- **Adaptive** safety logic: the same certified safety floor, plus a learned layer that
  reads what the person is doing and lets the robot keep working when it is genuinely safe
  to — while never being allowed to make the robot *faster* than the certified floor.

The task has to be a real collaborative job where a fixed distance is genuinely in the
way, so the difference between the two shows up as something you can measure.

### The job and the roles

The job is installing ceiling panels. One **Panel Cycle** installs one panel, and it
repeats. Two players share the space:

- **The robot** is a lifting/holding jack. It has a gripper/vacuum end-effector that grabs
  the panel and can release it. **Nothing is ever bolted to the robot** — it only ever
  *holds* the panel. So the robot is never load-bearing after the bolts go in; it can
  always let go and back away.
- **The human participant** does three things across the cycle: **loader** (puts the panel
  on the robot), **aligner** (nudges the panel into place), and **bolter** (drives the
  bolts into the ceiling).

### The five phases

Each phase below lists: what the robot is doing, what the human is doing, how close they
are, the ISO/TS 15066 **collaborative mode** that governs it, and whether it is a
**measurement window** (a phase where static and adaptive can differ, so we score it).

**P1 — LOAD.** The arm is lowered to waist height and parked. The human slides the panel
onto the end-effector plate. They are close, but the arm is not moving.
Robot: parked. Human: loading. Proximity: close. Mode: **safety-rated monitored stop**
(the arm is held still). *Not a primary measurement window* — it is a distinct task step,
not a place static and adaptive differ.

**P2 — TRANSIT / LIFT.** The robot lifts the panel to the ceiling and aligns it flush with
the frame. **At the same time** the human is still in the shared space — fetching the bolt
gun, repositioning their platform. Robot and human both move, close together.
Robot: lifting + aligning. Human: preparing. Proximity: shared workspace. Mode:
**speed-and-separation monitoring (SSM)**. **Measurement window.** Static SSM uses the
worst-case distance, so every cycle it either forces the human out of that zone or
protective-stops. Adaptive recognises "robot transiting, human on a predictable prep path,
not closing" and shrinks the zone, so the two can work at the same time.

**P3 — HAND-GUIDED FINE ALIGNMENT (the v2 addition).** Real panels never line up with the
bolt holes on the first try. The robot holds the panel **compliantly** (it yields to a
push), and the human nudges it a few millimetres **by hand**. This is deliberate physical
**contact**. Robot: compliant hold. Human: nudging by hand. Proximity: **contact**. Mode:
**hand-guiding** (ISO/TS 15066). **Measurement window — maximum divergence.** Static logic
essentially **forbids** this: to a fixed-distance controller, a hand at the panel is a
zone breach, so it protective-stops and the task cannot proceed. Adaptive **permits** it —
not by the learned layer overriding anything, but because the robot's **certified**
compliant-hold mode is recognised, and in that mode contact is expected and permitted at a
low, force-limited "compliant-hold" speed. This respects the envelope invariant (Change 1):
the learned layer can only add caution; hand-guiding is unlocked by a *certified mode*, not
by a learned belief.

**P4 — BOLT / HOLD.** The human drives the bolts through the panel **into the ceiling
structure** while the robot holds the panel **dead still**. Robot: held still (equivalent
to a safety-rated monitored stop). Human: bolting. Proximity: contact. Mode: **safety-rated
monitored stop**. **Explicitly NOT a measurement window.** Here static and adaptive are
**identical** — both hold the robot still. We say this plainly in the paper because
*measuring this hold* was the exact confusion the v2 redesign removed: a stopped robot is a
stopped robot, and comparing "how well each controller holds still" measures nothing.

**P5 — RELEASE / RETRACT.** The robot releases the panel (now bolted to the ceiling) and
lowers, while the human finishes the last bolt and steps down. Robot and human move, close
together, again. Robot: releasing + lowering. Human: finishing / descending. Proximity:
shared workspace. Mode: **speed-and-separation monitoring (SSM)** (the robot holds still
until the human has cleared the safety distance, then lowers). **Measurement window.** As
in P2, static reduces speed for a person who is actually moving *away*; adaptive recognises
the retreat and keeps working.

So three of the five phases are measurement windows (P2, P3, P5); the other two (P1 load,
P4 bolt) are not. Two of the three windows are speed-and-separation phases (P2, P5) where
**minimum separation** is a real safety number; the third (P3) is a contact phase where
~0 m of separation is *by design*, so P3 is scored on **feasibility** (does the controller
permit the task) rather than distance.

### Why this task, and not the obvious alternatives

We deliberately rejected three simpler-sounding designs:

- **A handover cycle** (human hands the panel to the robot, or vice versa). Rejected: it
  reintroduces a person manually holding an overhead panel — the ergonomic hazard the whole
  project exists to remove — and it creates a *forced-contact* moment whose ISO/TS 15066
  collaborative mode is ambiguous (is it hand-guiding? power-and-force-limiting? a plain
  transfer?). Ambiguity in the governing mode is fatal for a safety comparison.
- **The robot picking panels off a stack itself.** Rejected: that is an *orthogonal*
  problem — robot perception and grasping of a bin of parts — with no bearing on the safety
  question. It would add a large, unrelated engineering risk and dilute the contribution.
- **A hold-only task (no hand-guiding).** Rejected: with no contact phase, the divergence
  between static and adaptive is small, because speed-and-separation monitoring already
  solves the transit phases well. The hand-guiding phase is what makes the static/adaptive
  gap near-binary (feasible vs infeasible), which is the sharpest evidence for the paper.

The Panel Cycle keeps the human out of load-bearing holds, keeps every phase in one
unambiguous collaborative mode, and puts the decisive comparison (P3) front and centre.

### Participant protocol

- **Briefing.** The participant is told the task (load, tend, hand-guide, bolt, release),
  the cued-event signals, and the safety measures (e-stop within reach, continuous
  supervision, a lightweight surrogate panel). They are **not told** which safety
  controller is active, so their behaviour is not biased by it.
- **Conditions.** Two controller conditions: **static** (fixed-zone) and **adaptive**. Each
  participant completes **N complete Panel Cycles per condition** (N fixed during pilot
  calibration; enough cycles for stable per-condition estimates).
- **Counterbalancing.** The order of the two conditions is **counterbalanced across
  participants** (half do static first, half adaptive first) to cancel out learning and
  fatigue effects.
- **Per-condition metrics.** For each condition we log, per phase and overall: **cycle
  time**, **protective-stop count**, **minimum separation distance**, and **human idle
  time** (time the human waits on the robot). The speed-and-separation windows (P2, P5) and
  the hand-guiding window (P3) are reported **separately** from the P4 hold.
- **Subjective measures.** After each condition the participant fills in a short
  **fluency / trust questionnaire** (perceived smoothness of the collaboration and trust in
  the robot), so we capture the human's experience, not just the machine's numbers.

### Hypothesis

Adaptive **matches** static on safety — **zero separation violations**, identical response
to the cued slip — while **improving** cycle time, protective-stop count, and human idle
time. The hand-guiding phase (P3) is expected to be **near-binary**: **feasible under
adaptive, effectively infeasible under static**, because a fixed-distance controller cannot
permit the intended contact.

Code: `sim/scenario.py` (the Panel Cycle generator, with per-sample phase + certified
collaborative mode), `panel_cycle.py` (the phase / mode vocabulary), `metrics.py`
(`compute_phase_metrics` for the per-phase reporting), `controllers/controllers.py` (the
mode-aware certified floor). Tests: `test_scenario_v2_emits_all_phases_and_modes`,
`test_hand_guide_feasible_for_envelope_infeasible_for_fixed_zone`,
`test_collaborative_mode_governs_envelope_floor`, `test_hand_guide_still_stops_for_fast_lunge`,
`test_measurement_windows_exclude_hold_bolt_and_load`,
`test_adaptive_beats_static_burden_at_equal_safety`.

---

## Change 1 — Safety-envelope architecture (runtime assurance / shielding)

**What changed.** New `src/hrc_safety/envelope.py` implements the ISO/TS 15066
speed-and-separation stop distance using the **measured** approach speed:

```
S(t) = max(0, v_proj(t)) * T + C + Sa
```

This is a *state-blind, speed-aware* function of geometry alone. It maps the current
gap `d - S` to the **maximum permissible speed fraction**: `0` at or inside `S`,
ramping linearly to `1` across a band, full speed beyond. The controller is refactored
into `EnvelopeAdaptiveController`, whose command is:

```
final speed = min( envelope_max_speed , lhmm_caution_cap )
```

with the fixed-RED hard-stop invariant kept on top. The learned layers can only pull
the command **down**, never up. Locked by `test_adaptive_never_exceeds_envelope`
(README non-negotiable #4).

**WHY (the one line for the viva): "the smart part can only add caution, never remove
it."** In the sem-1 design the learned model could reason its way *up* to full speed
inside the warning band ("operator is retreating → don't slow"). That put a
non-certified, learned component on the safety-critical path: a recognition error could
*raise* the robot's speed toward a person. Certifying a learned model to a safety
standard is the hard, unsolved problem in the field. The envelope sidesteps it. It is a
certified floor computed from geometry and measured speed; the model sits on top as a
*shield* that only ever adds caution. A wrong belief now makes the robot too slow (an
annoyance), never too fast (a hazard). This is the standard **runtime-assurance /
safety-shielding** pattern, and it is what lets us bolt a learned layer onto a
safety loop honestly.

**Why measured speed, not fixed K.** The fixed zone assumes the worst-case human
approach speed (`K = 1.6 m/s`) at all times, so it stops the robot for a stationary
worker standing near it "just in case they lunge." The envelope reads the *actual*
closing speed: a stationary worker (`v_proj ≈ 0`) yields `S = C + Sa`, so the robot may
keep working. When the operator genuinely approaches at `K`, `S` rises to `K·T + C + Sa`
— exactly the old fixed red radius. **The envelope is never less safe than the fixed
zone at the speed the fixed zone assumed; it is only less conservative when the person
is demonstrably slower.**

Code: `envelope.py`, `controllers/controllers.py`. Tests: `test_adaptive_never_exceeds_envelope`,
`test_red_zone_always_stops_adaptive_even_if_model_says_working`.

---

## Change 2 — Horizon prediction (replaces one-step `p@A`)

**What changed.** New `src/hrc_safety/horizon.py`. `time_to_breach(d, v_proj, a_proj,
red_radius, horizon)` extrapolates the operator's motion under constant acceleration
and returns the time until they cross the red radius. It is fused with the state
posterior:

```
imminence = sigmoid( steepness * (horizon - time_to_breach) )   # gated by closing speed
risk      = max( p_hazard , imminence )
```

`prediction.py` (one-step `p_{t+1} = normalize(p_t @ A)`, paper Eq.1) is kept for
backward compatibility and for the ablation, but is marked **superseded** as the
anticipation mechanism. New metric `anticipation_lead_time_s` = red-radius breach time
minus stop-command time (positive = stopped *before* the breach).

**WHY (the one line): "predict where they'll BE, not the next tick's label."** At 60 Hz,
one step is 16 ms, and the HMM's transition matrix is deliberately sticky, so
`p_{t+1}` is almost identical to `p_t`. Calling a 16 ms, barely-changed posterior
"anticipation" is close to vacuous — it cannot buy meaningful lead time before a breach.
Anticipation is a **kinematic** question (where will the body be), not a labelling one.
We extrapolate the trajectory over a real ~0.5 s horizon and ask whether it crosses the
boundary. Eq.1 survives as a *component* — it is the transition-prediction half of the
forward filter — but it is no longer the claim.

**Two guards that matter (and why raw extrapolation fails without them).** Velocity and
especially acceleration are finite-difference estimates over a jittery position sensor,
so raw `a_proj` routinely reads ±30 m/s² — three times gravity, impossible for a human.
Fed into `0.5·a·τ²` that noise predicts an imminent breach almost every tick. So we
**(1) clamp** the extrapolated acceleration to a human-plausible bound (~0.4 g), and
**(2) gate** imminence on a minimum sustained *closing* speed — a stationary worker 16 cm
outside the boundary whose jitter momentarily reads as "closing" is not a breach. With
both guards the predictor fires cleanly on the cued slip and ignores working sway,
lateral darts, and retreats.

Code: `horizon.py`, `controllers/controllers.py`, `metrics.py`. Tests:
`test_time_to_breach_kinematics_and_accel_clamp`, `test_fused_risk_gated_by_closing_speed`,
`test_full_system_anticipates_before_fixed_zone`.

---

## Change 3 — Three-rung comparison + replay ablation

**What changed.** The comparison is now three rungs, all emitting the **identical**
`DecisionRecord`:

1. **`FixedZoneController`** — deployed practice (fixed distance threshold; alias of the
   old `StaticController`).
2. **`DynamicSSMController`** — the ISO/TS 15066 *speed-aware envelope alone*, no learned
   model. The **standards rung**: what a conscientious integrator could deploy without
   any ML.
3. **`EnvelopeAdaptiveController`** — the full system (envelope floor + state layer +
   horizon prediction).

New `scripts/replay.py` runs **any** controller over a logged trace (JSONL/positions or
a saved `.npz`) offline and emits metrics. `run_simulation.py` prints a 3-column table
plus **ablation** rows: *full minus prediction* and *full minus the state layer*.

**WHY (the one line): "remove one ingredient at a time to see what each buys."** With
three rungs you can attribute gains to their source: rung 1→2 isolates what
*speed-awareness* recovers; rung 2→3 isolates what *state + prediction* add. The replay
tool makes this **free** — once a trace is on disk, running another controller over it
costs nothing (no robot, no re-collection), so the ablation is just "hold the trace
fixed, swap one ingredient." It is also exactly how pilot data will be scored: drop the
recorded trace in, replay every rung, done. Building the controllers through one shared
harness (`src/hrc_safety/analysis.py`) means the script, the replay tool, the paper
tables, and the tests all report the *same* numbers — one construction path, no drift.

Code: `controllers/controllers.py`, `analysis.py`, `scripts/replay.py`,
`scripts/run_simulation.py`. Tests: `test_three_rungs_emit_identical_schema`.

---

## Change 4 — Distractors + specificity

**What changed.** `sim/scenario.py` gains two **cued distractor** events, ground-truth
labelled **not** hazard: (a) a fast **lateral dart** across the work face (high speed,
~zero closing), and (b) a sudden fast **retreat** (high speed, opening). In v2 both sit in
the **speed-and-separation measurement windows** — the dart in P2 (transit), the retreat in
P5 (release) — where separation is the safety quantity and a nuisance stop would actually
cost throughput. The single cued **slip** (the one true hazard) also sits in an SSM window
(P2), so it *must* stop the robot; contrast that with the identical-looking small
separation in P3 hand-guiding, which is safe because the certified mode is compliant hold —
proof that separation alone cannot decide, the collaborative mode must. The trace carries
`slip_windows` and `distractor_windows`; `metrics.py` reports **false-stop rate** on
distractor windows and **hazard sensitivity** on slip windows, so hazard evaluation reports
**sensitivity AND specificity**.

**WHY (the one line): "a controller that stops for any fast motion is useless."** A slip
is a fast motion near the robot. A lazy controller could ace a sensitivity-only test by
stopping for *every* fast motion — and be unusable in practice (constant nuisance stops).
The distractors are fast motions that are *not* hazards; a good controller must ignore
them. Reporting specificity is what separates "recognises danger" from "panics at
movement." (In simulation all three rungs reach specificity 1.0 with the closing-speed
gate; the distractors are there to make that a *measured* claim, and to catch any future
change that regresses it.)

Code: `sim/scenario.py`, `metrics.py`. Tests: `test_distractors_do_not_trigger_stops`.

---

## Change 5 — Metric redefinition (frozen; resolves the Table-I contradiction, option a)

**What changed.** The **primary efficiency outcome** is now `interruption_burden`: the
**time-integrated speed deficit** (`full speed − commanded speed`) over
**ground-truth-safe** periods, where "safe" **excludes** true-hazard (slip) windows and
red-zone occupancy. A zone-consistent reduced speed while *Working* counts toward burden
**equally for all conditions**. The old count metrics (stop/slowdown episodes,
`unnecessary_interruption_s`) are kept as **secondary**.

**WHY (the one line): "the scoreboard must count the thing you claim to improve."** The
sem-1 primary metric counted *any* stop or slowdown while the operator was
working/retreating as "unnecessary" — but Table I **prescribes** a slowdown for a working
operator in the warning band. So the adaptive controller was **penalised for doing
exactly what it was designed to do**; the metric contradicted the design (documented in
`docs/experiment_plan.md §5`). The fix (option a) narrows the outcome to a
speed-*deficit* integral applied **identically** to every controller. Because everyone is
charged the same way for a given true situation, the comparison isolates **contextual
reasoning** — *who reduces speed when they needn't* — rather than *who happens to follow
a fixed rule table*. Lower burden = less lost productivity, cleanly attributable.

**WHY over-arching (change 5's meta-lesson): "write down your bets before rolling the
dice."** Freezing the metric definition *before* looking at outcomes is what keeps the
result honest — you are not tuning the scoreboard to flatter the system. That is the
process discipline the redesign encodes.

**v2 consistency (not a re-tune, the same principle extended).** The Panel Cycle adds two
phases where a reduced or zero speed is *prescribed by the task*, not a controller failing:
hand-guiding (compliant-hold reduced speed) and the monitored-stop holds (P1, P4). Charging
those deficits as burden would repeat the *exact* Table-I category error this change fixed —
penalising a controller for doing what the task requires. So the burden integral is measured
over **speed-and-separation operation only** (P2 transit, P5 retract): the phases where a
slow-down is a *choice* the controller makes, and therefore the only place "who is cautious
when they needn't be" is a fair question. This is the same rule as before (exclude periods
where the reduction is warranted), now also excluding the non-SSM collaborative modes.

Code: `metrics.py`. Tests: `test_interruption_burden_excludes_hazard_and_red`,
`test_adaptive_beats_static_burden_at_equal_safety`.

---

## What did NOT change

- The **RED-zone protective stop** is still checked first and is absolute, in every rung
  (`test_red_zone_always_stops_adaptive_even_if_model_says_working`).
- Models are still **fitted from labelled data**, never the hand-set config priors.
- **Synthetic data never appears in reported results** — it validates the pipeline pilot
  data will flow through. All numbers in the committed tables are synthetic placeholders.

## Reproducing the numbers

```
python scripts/run_simulation.py        # 3-rung + ablation table; writes metrics JSON
python scripts/replay.py --controller all   # same, offline replay form
make paper                              # regenerate result tables; build PDF if latexmk present
pytest                                  # safety invariants are locked here
```
