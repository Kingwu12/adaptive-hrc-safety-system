# Publication analysis, October 2026

Status: working analysis for the conference-paper extension proposed by A/Prof Yihai Fang on 3 Oct 2026. All numbers below come from the raw participant captures (9.5 GB, 416 files). Participant-level outputs stay outside this public repository. Only aggregate results are committed, in `data/analysis/publication/`.

## 1. What changed from the FYP paper

| FYP paper (v3.1) | This analysis |
|---|---|
| 11 study codes "cannot be treated as 11 people" | Each code is one continuous 25 to 35 minute sitting with a full counterbalanced three-controller sequence. Helmet height from OptiTrack separates the codes the Xsens profile could not. |
| One pooled analysis | Pooled analysis of all 11 people, with the system version (section 2) reported as a factor |
| Stop counts and durations from the applied controller only | Exact replay of all three controllers, plus fixes, on identical recorded motion for all 97 trials |
| "Unnecessary stop" not measured | Hindsight definition: a stop is unnecessary if the person is outside the protective radius S0 and does not enter it within H seconds (H = 0.5, 1, 2 s) |
| End-to-end response "not measured" | Stop request to measured TCP standstill: median 0.156 s, 95th percentile 0.188 s, maximum 0.204 s (n = 215) |
| Hysteresis proposed as the next change | Tested offline. Onset dwell helps; a release hold makes things worse. A trunk-intent predictor removes most of the excess. |

## 2. Two system versions

| | v1, head column | v2, whole body |
|---|---|---|
| Sessions | 9 and 10 Sep | 16 and 17 Sep |
| Codes and trials | P13, P14, P15, P16, P17, P22; 52 trials, 95 min | P31, P32, P34, P35, P38; 45 trials, 86 min |
| Control distance | Helmet column | Nearest of 23 helmet-anchored Xsens segments |
| Logging | Applied decision | Applied decision and shadow decisions of all three controllers |

P13, before 12:00 on 9 Sep, ran an earlier predictive yellow-zone cap (commit c852471, kept as `src/hrc_safety/controllers/legacy_c852471.py`). All other trials ran the current logic. The recorded HMM is c852471 `pilot_hmm.json` (sha256 aa69fd8e with CRLF line endings).

**Replay fidelity.** Every sample of every trial matches the logged applied decision. In v2 it also matches the logged shadow decisions of the other two controllers: 105 of 105 trials, 100.0%.

## 3. Identity

- The Xsens MVN body profile was reused between people. Codes P14 and P15, and P32 and P34, have identical segment lengths to 0.1 mm. A 0.4162 m thigh profile appears for several people.
- OptiTrack helmet height (98th percentile) does not depend on that profile. It separates P14 (1.750 m) from P15 (1.810 m), and P32 (1.854 m) from P34 (1.874 m). Within-code spread is about ±0.01 m.
- The closest pairs are P13/P17 (1.900/1.905 m, different MVN profiles) and P32/P35 (1.854/1.853 m, different MVN profiles). The booking record should confirm these are different people.
- Twelve people completed the full study (King, 3 Oct). The 27 Sep backup holds complete nine-trial recordings for 11 of them. The twelfth is most likely P39 and P42 on 17 Sep: same helmet height (1.80 m) and profile. Only 3 reactive and 5 predictive trials are in the backup, and there are no fixed-zone trials. Codes P40 and P41 are absent, so the missing trials should be looked for on the lab PC.
- P23 and P24 on 10 Sep: 5 short predictive-only recordings of a person about 1.93 m tall, not one of the 11. Identity to be confirmed.
- **Consequence for v2.** For people measured with a reused profile, the whole-body distance came from a body model scaled for someone else. This is a distance-uncertainty term to report.

## 4. Primary results (all 11 people, 97 trials, 181 min, 782 protective-radius entries)

The unit of inference is the person. Rates are per minute of observed time. Paired differences use a percentile bootstrap over people and the Wilcoxon signed-rank test.

| Controller, identical inputs | Stop s/min | Brief stops/min | Unnecessary s/min (H = 1 s) | Entries with stop already requested | Mean lead before entry |
|---|---|---|---|---|---|
| Fixed zone | 18.65 | 1.73 | 0.32 | 100% | 0.704 s |
| Reactive SSM | 18.91 | 6.06 | 0.43 | 100% | 0.716 s |
| Predictive SSM (as run) | 20.33 | 14.88 | 1.14 | 100% | 0.828 s |
| Predictive, onset dwell 6 | 19.50 | 6.36 | 0.66 | 100% | 0.794 s |
| Predictive, trunk intent | 19.35 | 10.31 | 0.50 | 100% | 0.767 s |

- **Predictive vs fixed.**
  - It stops earlier before each entry: +0.112 s (95% CI 0.079 to 0.145; 11 of 11 people; p = 0.001).
  - It adds unnecessary stopping: +0.82 s/min (95% CI 0.26 to 1.50; 11 of 11 people; p = 0.001).
- **Predictive vs reactive.** Same pattern: +0.102 s of lead and +0.71 unnecessary s/min, in 11 of 11 people.
- **Onset dwell of 6 ticks.** Unnecessary stopping falls by 0.48 s/min (11 of 11 people, p = 0.001).
- **Trunk-intent fix.** It only changes the v2 sessions, because v1 control already used the head column. See section 4b.

## 4b. Whole-body version (v2: 5 people, 45 trials, 464 protective-radius entries)

With 5 people, the smallest two-sided Wilcoxon p is 0.0625, so sign consistency is reported alongside the bootstrap interval.

| Controller, identical inputs | Stop s/min | Brief stops/min | Unnecessary s/min (H = 1 s) | Entries with stop already requested | Mean lead before entry |
|---|---|---|---|---|---|
| Fixed zone | 17.75 | 3.73 | 0.18 | 100% | 0.418 s |
| Reactive SSM | 18.33 | 13.18 | 0.42 | 100% | 0.438 s |
| Predictive SSM (as run) | 20.88 | 24.66 | 1.89 | 100% | 0.585 s |
| Predictive, onset dwell 6 | 19.44 | 13.09 | 0.94 | 100% | 0.545 s |
| Predictive, trunk intent | 18.72 | 14.61 | 0.49 | 100% | 0.481 s |

The paired differences per person:

- **Predictive vs fixed.** 1.7 more unnecessary s/min (95% CI 0.9 to 2.7; higher for 5 of 5 people). It also starts stopping 0.166 s earlier before each entry (95% CI 0.145 to 0.187; 5 of 5 people).
- **Trunk intent vs predictive as run.** 1.4 fewer unnecessary s/min (95% CI 0.7 to 2.2; lower for 5 of 5 people). It keeps a 0.045 to 0.065 s earlier stop than reactive and fixed (5 of 5 people).
- **Safety on real movement.** Under every controller and variant, a stop was already requested at 100% of the 782 entries into S0 across all trials. No controller ever requested motion inside S0.
- **Closed loop.** The TCP moved inside S0 only within the 0.5 s braking window after a stop request. Elsewhere, TCP speed with zero speed scaling was vibration of the held arm, at most 3 mm of displacement.

### Mechanism

The intrusion predictor read the closing speed of the nearest body segment. In overhead panel work that segment is usually an arm, hand or foot: upper arm, forearm and hand gave 55% of predictor stop samples, and foot and toe 37%. Only 31% of v2 predictor stop samples (n = 3,383) had the trunk itself closing at 0.6 m/s or faster. Normal reaching to the robot-held panel was therefore treated as intrusion. A trunk-intent predictor fixes this:
- closing speed and acceleration come from the trunk (helmet column)
- the distance limit, envelope and red boundary still use the whole body

A release hold makes things worse: 2.8 unnecessary s/min across all trials.

### Task-level finding

Under every controller the robot is stopped about 30% of the time, and over 94% of that stopping is necessary by the hindsight rule. The ceiling-panel task places the worker inside the protective distance for long periods. The productivity limit therefore comes from using SSM during close-contact phases, not from the controller choice. This motivates switching mode by task phase: hand guiding or force limiting while the worker is under the panel, which the design already models but the study did not exercise.

## 5. v1 (head column: 6 people, 52 trials)

The same safety result holds: 100% of 318 entries were covered. The predictive excess is small: 0.08 unnecessary s/min (95% CI 0.04 to 0.12). Predictive brief stops are 6.7/min, against 0.06/min for fixed and 0.13/min for reactive. The predictive lead is 0.067 s (6 of 6 people). The trunk-intent variant is identical to the original here, because head-column geometry already is the trunk.

## 6. Still to do

1. Recover the twelfth person's missing trials from the lab PC (codes P40 and P41, or other 17 Sep files). Confirm P13/P17, P32/P35 and P23/P24 against the booking list.
2. Quantify distance error from profile reuse: helmet height against the MVN model head height per person.
3. Measure sensing-to-command latency: the Xsens and OptiTrack age fields, plus the tick.
4. A confirmatory physical session with:
   - the trunk-intent predictor
   - a frozen version
   - re-measured MVN profiles per person
   - a persistent participant ID
   - phase-dependent collaborative mode

## Reproduce

```text
python scripts/identity_from_body_model.py   --captures <raw>/data/xsens --out <private>/identity
python scripts/identity_from_helmet_height.py --captures <raw>/data/xsens --out <private>/identity
python scripts/analyse_counterfactual.py      --captures <raw>/data/xsens --out <private>/counterfactual \
       --model <c852471 pilot_hmm.json> --extra P39 P42
python scripts/summarise_counterfactual.py    --inp <private>/counterfactual/counterfactual-per-trial.json \
       --codes P31 P32 P34 P35 P38 --name summary-v2-whole-body
python scripts/diagnose_geometry_and_motion.py --captures <raw>/data/xsens --out <private>/diagnostics
```
