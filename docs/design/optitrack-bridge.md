# OptiTrack Integration — Scoping Proposal

Companion to `docs/experiment_plan.md`. Scope for wiring the lab's OptiTrack
system into the existing pipeline. Nothing here is speculative hardware — the
lab owns the tracker; the needed code is deliberately thin. Three components,
in build order.

## 1. NatNet bridge client (`src/hrc_safety/mocap/natnet_bridge.py`)

Motive streams rigid-body poses over NatNet (UDP multicast). The bridge's whole
job: subscribe, extract ONE rigid body's (x, y, z), timestamp it, and call
`FeatureExtractor.push(t, position)` — the exact same entry point the simulator
feeds today. Nothing downstream changes; that is the point.

Decisions proposed:
- **Track one rigid body (torso-mounted marker cluster), not a skeleton.**
  The sim, the LHMM features, and the envelope all model the operator as a
  single point. A skeleton adds Motive configuration burden and zero model
  benefit for this study. (Future work can revisit.)
- **Vendor the NatNet Python client** (Motive ships `NatNetClient.py` in its
  SDK samples) rather than adding a pip dependency of uncertain maintenance.
- Resample/hold to the pipeline's 60 Hz tick (`configs/default.yaml
  sample_rate_hz`); Motive typically streams 120–240 Hz, so this is a decimate,
  never an upsample. Drop-out handling: hold last position, set a staleness
  flag; >150 ms stale => treat as tracking loss => controllers fall back to
  worst-case (same posture as the fixed zone) — never optimistic.

## 2. Raw-stream recorder (`scripts/record_mocap.py`)

Append-only JSONL: `{t, pos, rb_tracked, motive_timestamp}` per tick, before
any filtering. Every pilot session becomes replayable offline through ALL
rungs via the existing `scripts/replay.py` path — one human session, three
controller results, zero extra lab time. This is also the labelled-data source
for `fit_transitions` / `fit_emissions` (teammates label the video; timestamps
join on `t`).

## 3. Calibration glue (`scripts/calibrate_mocap.py` + lab-day checklist)

Two one-time measurements per cell setup:

- **Mocap -> robot base transform.** Touch the robot TCP to 3–4 taped floor
  points (read poses from the controller), place a marker wand on the same
  points (read from Motive), solve the rigid transform (Kabsch). Store as
  `configs/mocap_extrinsics.yaml`; the bridge applies it so all positions are
  in robot-base frame — the frame every zone and envelope already assumes.
- **Measure `Sa`** (experiment_plan checklist item): operator stands still at
  3 stances for 30 s each; `Sa` = a high quantile (p99) of position residual
  magnitude through the full mocap->bridge chain. Feeds the recomputed `S0`.

## Binding physical constraint (restated)

Mocap volume ~4 x 4 x 2.5 m is SMALLER than the cell. Every stance — including
the prep stance inside the worst-case zone and the slip target — must sit
inside the tracked volume. Verify with the wand before taping the floor
(already on the pilot checklist).

## Non-goals (v1)

No skeleton tracking, no multi-body, no ROS, no live visualisation, no Kalman
smoothing (the FeatureExtractor's slope fit already tolerates jitter; add
filtering only if measured Sa is unacceptable).

## Sequencing & effort

| Piece | ~Size | When |
|---|---|---|
| NatNet bridge + staleness fallback | ~150 lines + tests | now — testable against a fake NatNet feed, no lab needed |
| Recorder | ~50 lines | now, same job |
| Calibration script + checklist | ~100 lines | code now; RUN requires lab access |

## MUHREC impact — flag for the team

Participants wear a torso marker cluster (vest or clip-on). That is wearable
instrumentation and must be described in the ethics protocol (equipment worn,
comfort, no recording of identifiable features by the mocap itself). Include it
in THIS week's submission — adding it later means an amendment on the critical
path. Video recording for labelling is a separate, already-planned consent item.
