# Experiment Plan — Adaptive vs Static HRC Safety

Companion to the paper *"Comparing Static and Adaptive Safety Logic in Human-Robot Ceiling
Panel Installation"* (Wu, Siniakov, Magila, Monash 2026). This document covers the physical
setup, the pilot calibration that produces the REPORTED numbers, the ethics constraints on
the simulated hazard, and one design finding surfaced during simulation.

## 1. Physical footprint

| Item | Value | Note |
|------|-------|------|
| Cell | ~3 × 4 m | working area around the robot |
| Motion-capture volume | ~4 × 4 × 2.5 m (OptiTrack) | **the binding constraint** — the tracked space is smaller than the cell; all stances must sit inside it |
| Robot | UR10 CB3, ~1.3 m reach | holds the lightweight surrogate panel |
| Fastening stances | ~1.1 m from the column | inside yellow (1.504 m), outside red (0.940 m) at defaults |
| Bench | ~1.9 m from the column | DERIVED = yellow_radius + bench_clearance (1.504 + 0.40) |

The robot's protective separation is measured to the **occupied column** (the vertical
segment of space the arm+panel sweep), not to the TCP point — a human under a 2.2 m-high
panel has ~0 m of separation even though the TCP is far overhead.

## 2. Zone geometry (defaults)

`S0 = K·T + C + Sa = 1.6·0.40 + 0.20 + 0.10 = 0.940 m` (red radius);
`yellow = yellow_margin · S0 = 1.6 · 0.940 = 1.504 m`.

`T` (end-to-end reaction plus stopping time), `Sa` (validated sensing/body-proxy
uncertainty), and the simplified occupied-column geometry in the config are **pilot
placeholders**. They must be measured or conservatively bounded before any reported
moving-participant controller comparison. The reduced equation used here is not itself a
complete ISO 13855/TS 15066 safety calculation or a certification result.

## 3. Pilot calibration checklist

Run once per hardware configuration, before collecting reported data:

- [ ] **Measure `T` end-to-end** — command → sensed → robot fully stopped (not a datasheet value).
- [ ] **Measure `Sa`** — operator position uncertainty from the mocap + body-model chain.
- [ ] **Recompute `S0`** from measured `T`, `Sa` and re-tape the red/yellow zones on the floor.
- [ ] **Fit the phase model from ≥ 3 complete labelled loops** — every loop must include
      approaching, working, and retreating. Record the experimenter-cued rapid
      intrusion in a separate event field without replacing the active task phase; use
      `scripts/train_pilot_hmm.py` to enforce this gate, then `fit_transitions` for `A`,
      `fit_emissions` for the Gaussian mixtures. Report phase accuracy/balanced accuracy
      separately from event sensitivity, specificity, false-stop rate, and latency.
      These produce the reported model; the config's hand-set numbers are cold-start priors only.
- [ ] **Verify the command path in URSim first**, then on hardware — full/reduced speed via
      the RTDE speed slider. Dashboard pause is only a research stop request; SSM with a
      participant requires an independently validated safety-rated stop path.
- [ ] Validate that the protected geometry conservatively covers the arm, tool, panel and
      their swept volume for every reported phase; a TCP-centred vertical column is not
      automatically sufficient.
- [ ] Confirm all stances and the slip target fall inside the OptiTrack volume.

## 4. Ethics notes

- The **simulated slip must be explicit in the ethics application** — the protocol
  deliberately induces a near-approach to the robot column.
- Slips are **experimenter-CUED at randomised times**, never participant-improvised. The cue
  timestamp is the exact **hazard-onset ground truth** used for response-latency scoring; a
  participant-improvised lunge would have no clean onset and could not be scored fairly.
- Participants are briefed that the robot will stop; the red-zone protective stop is active in
  BOTH conditions, so no condition is less safe than the other.

## 5. Documented finding (from today's simulation, 2026-07-06)

Paper **Table I prescribes reduced speed for Working-in-yellow**. But the paper's
**unnecessary-interruption** metric counts *exactly that* — any interruption (stop OR slowdown)
while the operator is, per ground truth, working or retreating — as unnecessary. So the
adaptive controller **fails H1 partly by its own design**: it correctly slows for a stationary
worker in the yellow band, and the metric then charges that slowdown against it. In simulation
the gap is small (~1 s of unnecessary interruption per ~17 s loop) but real.

**Options (decision pending King + supervisor):**

- **(a) — RECOMMENDED.** Narrow the metric definition to *stops + zone-inconsistent slowdowns*
  (i.e. slowdowns that don't match the operator's actual zone/activity). Keeps the controller
  conservative and makes the metric measure what it claims to measure.
- **(b)** Amend Table I to **full speed for stable Working in the outer yellow band**. Produces
  a bigger H1 effect but a harder safety argument to defend.

Either way the RED-zone protective stop and the pre-emptive hazard stop are untouched — this
is purely about how outer-yellow *working* is scored/handled.
