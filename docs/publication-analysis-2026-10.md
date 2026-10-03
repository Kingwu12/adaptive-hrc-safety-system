# Publication analysis, October 2026

Status: working analysis for the conference-paper extension proposed by A/Prof Yihai Fang on 3 Oct 2026. All numbers below come from the raw participant captures (9.5 GB, 416 files). Participant-level outputs stay outside this public repository. Only aggregate results are committed, in `data/analysis/publication/`.

## 1. What changed from the FYP paper

| FYP paper (v3.1) | This analysis |
|---|---|
| 11 study codes "cannot be treated as 11 people" | Each code is one continuous 25 to 35 minute sitting with a full counterbalanced three-controller sequence. Helmet height from OptiTrack separates the codes the Xsens profile could not. |
| 11 codes, twelfth participant unused | All 12 people pooled, with the system version (section 2) reported as a factor |
| Stop counts and durations from the applied controller only | Exact replay of all three controllers, plus fixes, on identical recorded motion for all 97 trials |
| "Unnecessary stop" not measured | Hindsight definition: a stop is unnecessary if the person is outside the protective radius S0 and does not enter it within H seconds (H = 0.5, 1, 2 s) |
| End-to-end response "not measured" | Stop request to measured TCP standstill: median 0.156 s, 95th percentile 0.188 s, maximum 0.234 s (n = 226) |
| Hysteresis proposed as the next change | Tested offline. Onset dwell helps; a release hold makes things worse. A trunk-intent predictor removes most of the excess. |

## 2. Two system versions

| | v1, head column | v2, whole body |
|---|---|---|
| Sessions | 9 and 10 Sep | 16 and 17 Sep |
| Codes and trials | P13, P14, P15, P16, P17, P22; 52 trials, 95 min | P31, P32, P34, P35, P38, P39/P42; 53 trials, 111 min |
| Control distance | Helmet column | Nearest of 23 helmet-anchored Xsens segments |
| Logging | Applied decision | Applied decision and shadow decisions of all three controllers |

P13, before 12:00 on 9 Sep, ran an earlier predictive yellow-zone cap (commit c852471, kept as `src/hrc_safety/controllers/legacy_c852471.py`). All other trials ran the current logic. The recorded HMM is c852471 `pilot_hmm.json` (sha256 aa69fd8e with CRLF line endings).

**Replay fidelity.** Every sample of every trial matches the logged applied decision. In v2 it also matches the logged shadow decisions of the other two controllers: 105 of 105 trials, 100.0%.

## 3. Identity

- The Xsens MVN body profile was reused between people. Codes P14 and P15, and P32 and P34, have identical segment lengths to 0.1 mm. A 0.4162 m thigh profile appears for several people.
- OptiTrack helmet height (98th percentile) does not depend on that profile. It separates P14 (1.750 m) from P15 (1.810 m), and P32 (1.854 m) from P34 (1.874 m). Within-code spread is about ±0.01 m.
- The closest pairs are P13/P17 (1.900/1.905 m, different MVN profiles) and P32/P35 (1.854/1.853 m, different MVN profiles). The booking record should confirm these are different people.
- **Twelve people took part, and all 12 are counted.** Eleven have complete or near-complete sittings: 8 or 9 of 9 trials. The twelfth person, recorded under codes P39 and P42 on 17 Sep (same helmet height of 1.80 m and same profile), has 8 recorded trials: 3 reactive and 5 predictive. There are no fixed-zone trials, and no further data exists (King, 3 Oct).
- **How the twelfth person is used.** Their sessions ran v2 with shadow logging, so every sample carries all three controllers' requests. The open-loop comparison is therefore complete for that person, on the motion that was recorded. Only the closed-loop fixed-zone condition is missing.
- **Caveats for the twelfth person.**
  - These trials were flagged for phase order and a capture rate of about 26 Hz, against about 38 Hz elsewhere.
  - At the lower rate a dwell measured in ticks lasts longer in seconds, so the dwell variants are slightly stricter for this person.
  - A sensitivity analysis without them gives the same direction for every contrast.
- P23 and P24 on 10 Sep: 5 short predictive-only recordings of a person about 1.93 m tall. They are not counted as a participant.
- **Consequence for v2.** For people measured with a reused profile, the whole-body distance came from a body model scaled for someone else. This is a distance-uncertainty term to report.

## 4. Primary results (all 12 people, 105 trials, 206 min, 970 protective-radius entries)

The unit of inference is the person; P39 and P42 are merged as one person. Rates are per minute of observed time. Paired differences use a percentile bootstrap over people and the Wilcoxon signed-rank test. Replay fidelity is 100% on all 105 trials.

| Controller, identical inputs | Stop s/min | Brief stops/min | Unnecessary s/min (H = 1 s) | Entries with stop already requested | Mean lead before entry |
|---|---|---|---|---|---|
| Fixed zone | 18.50 | 2.16 | 0.30 | 100% | 0.688 s |
| Reactive SSM | 18.82 | 6.65 | 0.44 | 100% | 0.702 s |
| Predictive SSM (as run) | 20.25 | 15.34 | 1.20 | 100% | 0.798 s |
| Predictive, onset dwell 6 | 19.40 | 6.99 | 0.69 | 100% | 0.768 s |
| Predictive, trunk intent | 19.23 | 10.58 | 0.50 | 100% | 0.746 s |

- **Predictive vs fixed.**
  - It stops earlier before each entry: +0.107 s (95% CI 0.076 to 0.139; 12 of 12 people; p = 0.0005).
  - It adds unnecessary stopping: +0.90 s/min (95% CI 0.36 to 1.52; 12 of 12 people; p = 0.0005).
- **Predictive vs reactive.** Same pattern: +0.096 s of lead and +0.76 unnecessary s/min, in 12 of 12 people.
- **Onset dwell of 6 ticks.** Unnecessary stopping falls by 0.51 s/min (12 of 12 people, p = 0.0005).
- **Trunk-intent fix.** It changes only the v2 sessions, because v1 control already used the head column. See section 4b.
- **Safety on real movement.** Under every controller and variant, a stop was already requested at 100% of the 970 entries into S0. No controller ever requested motion inside S0.
- **Closed loop.**
  - Stop request to measured TCP standstill: median 0.156 s, 95th percentile 0.188 s, maximum 0.234 s (n = 226).
  - The TCP moved inside S0 only while braking from an already-requested stop: median 0.03 s, at most 0.125 s after the request. The closest separation while the arm moved under program control was 0.54 m.
- **Physical contact with the held panel.** For 6.5 s in total, the TCP registered motion with zero speed scaling. The arm started from rest, moved a few mm, and sprang back while the person was inside S0. Five of the 12 people did this, which means they pushed the robot-held panel. Workers do touch the panel under SSM, which supports a contact-capable mode during installation.

## 4b. Whole-body version (v2: 6 people, 53 trials, 652 protective-radius entries)

With 6 people, the smallest two-sided Wilcoxon p is 0.031.

| Controller, identical inputs | Stop s/min | Brief stops/min | Unnecessary s/min (H = 1 s) | Entries with stop already requested | Mean lead before entry |
|---|---|---|---|---|---|
| Fixed zone | 17.62 | 4.27 | 0.16 | 100% | 0.477 s |
| Reactive SSM | 18.24 | 13.18 | 0.45 | 100% | 0.497 s |
| Predictive SSM (as run) | 20.63 | 23.95 | 1.89 | 100% | 0.610 s |
| Predictive, onset dwell 6 | 19.25 | 13.21 | 0.94 | 100% | 0.578 s |
| Predictive, trunk intent | 18.59 | 14.44 | 0.50 | 100% | 0.532 s |

- **Predictive vs fixed.** +1.73 unnecessary s/min (95% CI 1.07 to 2.50) and a +0.146 s earlier stop (95% CI 0.104 to 0.180). Both hold for 6 of 6 people (p = 0.031).
- **Trunk intent vs predictive as run.**
  - −1.39 unnecessary s/min (95% CI 0.82 to 2.06 lower).
  - −2.0 stop s/min.
  - −9.5 brief stops/min.
  - All three hold for 6 of 6 people (p = 0.031).
- **Trunk intent vs fixed and reactive.**
  - It keeps an earlier stop: +0.060 s over fixed and +0.040 s over reactive (6 of 6 people).
  - Its unnecessary stopping is close to reactive's: +0.06 s/min (95% CI 0.04 to 0.07).

### Mechanism

The intrusion predictor read the closing speed of the nearest body segment. In overhead panel work that segment is usually an arm, hand or foot: upper arm, forearm and hand gave 55% of predictor stop samples, and foot and toe 37%. Only 31% of v2 predictor stop samples (n = 3,383) had the trunk itself closing at 0.6 m/s or faster. Normal reaching to the robot-held panel was therefore treated as intrusion. A trunk-intent predictor fixes this:
- closing speed and acceleration come from the trunk (helmet column)
- the distance limit, envelope and red boundary still use the whole body

A release hold makes things worse: 2.97 unnecessary s/min across all 12 people.

### Task-level finding

Under every controller the robot is stopped about 31 to 34% of the time, and 94 to 98% of that stopping is necessary by the hindsight rule. The ceiling-panel task places the worker inside the protective distance for long periods. The productivity limit therefore comes from using SSM during close-contact phases, not from the controller choice. This motivates switching mode by task phase: hand guiding or force limiting while the worker is under the panel, which the design already models but the study did not exercise.

## 5. v1 (head column: 6 people, 52 trials)

The same safety result holds: 100% of 318 entries were covered. The predictive excess is small: 0.08 unnecessary s/min (95% CI 0.04 to 0.12). Predictive brief stops are 6.7/min, against 0.06/min for fixed and 0.13/min for reactive. The predictive lead is 0.067 s (6 of 6 people). The trunk-intent variant is identical to the original here, because head-column geometry already is the trunk.

## 6. Still to do

1. Confirm P13/P17 and P32/P35 as different people against the booking list, and confirm who P23/P24 was.
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
       --merge P39=P39/P42 P42=P39/P42 --name summary-all
(add --codes P31 P32 P34 P35 P38 P39/P42 --name summary-v2-whole-body for the v2 subset)
python scripts/diagnose_geometry_and_motion.py --captures <raw>/data/xsens --out <private>/diagnostics
```
