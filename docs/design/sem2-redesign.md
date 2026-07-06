# Semester-2 Redesign — Adaptive HRC Safety System

Companion to the paper *"Comparing Static and Adaptive Safety Logic in Human-Robot
Ceiling Panel Installation"* (Wu, Siniakov, Magila, Monash 2026). This is the design
record for the five sem-2 changes. Each section states **what changed**, gives a
**plain-English WHY** you can defend in a viva, and points at the code and tests.

The thread running through all five: **make the safety argument something you can
certify, and make the scoreboard measure the thing you claim to improve.**

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
~zero closing), and (b) a sudden fast **retreat** (high speed, opening). The trace now
carries `slip_windows` and `distractor_windows`. `metrics.py` reports **false-stop rate**
on distractor windows and **hazard sensitivity** on slip windows, so hazard evaluation
reports **sensitivity AND specificity**.

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

Code: `metrics.py`. Tests: `test_interruption_burden_excludes_hazard_and_red`.

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
