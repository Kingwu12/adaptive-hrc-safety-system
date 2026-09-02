# Pre-study qualification runbook

## Decision

Use the ten planned full-body Xsens runs to qualify the final acquisition and
control setup. They are not ten independent people and they do not, by
themselves, improve population generalisation. The active model stays frozen
unless these runs expose a material implementation or sensing change; reported
participant data is never used to retune it.

The current model recognises the task phases `approaching`, `working`, and
`retreating` from OptiTrack head-to-robot geometry. Full-body Xsens is recorded
as a synchronised secondary research source. It must not be described as a live
controller input until a new feature set is separately defined and validated.

## Before run 1

- Reconcile the exact task and cued rapid-intrusion event with the approved
  protocol. Do not improvise a real fall or trip.
- Put the final robot program, tool, panel, floor marks, OptiTrack rigid body,
  Xsens suit configuration, networks and safety chain in the positions intended
  for the participant study.
- Confirm the three known degraded Xsens sensor locations are resolved or
  explicitly documented; do not silently treat inferred limb motion as direct
  measurement.
- Start native recording in MVN Analyze using one unique filename for the run.
- Require the console to show Xsens 23/23, live OptiTrack, a real model digest,
  and a calibration mark less than five minutes old.

## Every run

1. Keep one operator, one script and one approved cued-event definition. Vary
   normal pace naturally, but do not invent new hazards.
2. Enter the visible native MVN filename/path and tick confirmation only after
   native recording is actually running.
3. Complete the guided sequence without manually rewriting labels afterward.
4. Stop native MVN recording, save it, and verify the Windows file exists and is
   non-empty before beginning the next trial.
5. Preserve every aborted or failed attempt. A failed attempt is evidence about
   the system; it is not silently deleted or renamed into a pass.

## After run 10

Replace the pilot ID/glob below with the files from this batch:

```bash
python scripts/verify_xsens_capture.py data/xsens/P06-T*.jsonl \
  --trial-batch --min-captures 10 \
  --report data/verification/prestudy-xsens-batch.json
```

The batch passes only if all ten Mac files contain complete 23-segment poses,
advancing counters, actual motion, valid phase/event labels, acceptable
OptiTrack freshness, unique native-MVN references and the same real model
digest. Separately compare the ten referenced names with the files visible on
the Windows laptop.

Commit the verified implementation, then freeze it:

```bash
python scripts/freeze_study_release.py \
  data/verification/prestudy-xsens-batch.json
python scripts/research_readiness.py --stage collection
```

The freeze command refuses a dirty implementation, a model below 0.80 offline
participant-held-out development accuracy, a model mismatch, or fewer than ten
passing qualification captures. The collection-readiness command will still
block until physical stopping time, sensing uncertainty, protected geometry,
safety-rated output, controller integration, ethics/protocol reconciliation and
analysis-plan freeze have real evidence. After collection, run
`python scripts/research_readiness.py --stage report`; that second stage also
requires the untouched final evaluation and real, non-synthetic results.

## Participant-study rule

Once the release is frozen, do not retrain, change thresholds, alter labels,
change the primary metric, or selectively exclude runs after seeing participant
outcomes. A required change means a new release made before restarting reported
collection. The independent hazard-response path remains kinematic and
fail-closed; phase accuracy is not the safety barrier.
