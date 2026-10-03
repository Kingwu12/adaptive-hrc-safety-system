# Publication analysis, October 2026

Status: working analysis for the conference-paper extension proposed by A/Prof Yihai Fang on 3 Oct 2026. All numbers below come from the raw participant captures (9.5 GB, 416 files). Participant-level outputs stay outside this public repository. The extracted raw captures were removed from the Mac on 3 Oct (moved to the Trash). The originals are in the Drive backup `Central-Windows-full-experiment-backup-20260927-111519/archives`, with checksums in `archive-parts.json`. Only aggregate results are committed, in `data/analysis/publication/`.

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
- The closest pairs are P13/P17 (1.900/1.905 m, different MVN profiles) and P32/P35 (1.854/1.853 m, different MVN profiles). King confirmed on 3 Oct that both pairs were different people.
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

## 6. Distance uncertainty: what anticipation buys

**The 100% coverage result comes from the design.** It holds at the measured distance because every controller shares the fixed red boundary at S0. The open question is what happens when the measured distance is wrong.

**Size of the error.** Helmet height (OptiTrack) minus the model head height (MVN) should be constant if the body model is scaled correctly. In v2 it varies by −2.1 to +4.8 cm around the median offset of 0.306 m. That is the body-profile reuse from section 3. The test below therefore moves the hindsight protective radius by ±5 and ±10 cm, with the controllers unchanged.

**With a radius 5 cm larger than measured** (the person is really 5 cm closer), the share of boundary entries with a stop already requested, across 12 people:

| Controller | Covered |
|---|---|
| Fixed zone | 31% |
| Reactive | 43% |
| Predictive as run | 67% |
| Trunk intent | 59% |

Per person:
- Predictive covers 38.8 points more than fixed (95% CI 30.7 to 46.4) and 29.8 points more than reactive. Both hold for 12 of 12 people (p = 0.0005).
- Trunk intent keeps 32.1 points over fixed and 23.0 points over reactive (12 of 12 people).
- The +10 cm results are the same.

The time the robot runs inside the enlarged radius follows the same order:

| Controller | Seconds over 206 min |
|---|---|
| Fixed zone | 96 |
| Reactive | 89 |
| Trunk intent | 80 |
| Predictive | 70 |

**This is the main safety argument for prediction.** Stopping earlier makes the system tolerant of distance error that a fixed boundary does not absorb. It turns the extra 0.1 s of lead time into a large, consistent margin.

## 7. Reaction chain

The measurable part of the chain, from 12 people:

| Stage | Median | p95 | p99 | Max |
|---|---|---|---|---|
| Xsens data age at the control tick | 0.016 s | 0.078 s | 0.157 s | 8.1 s (dropouts, handled by the body-evidence hold) |
| OptiTrack data age | 0.000 s | 0.016 s | — | — |
| Control tick interval, v2 | 0.031 s | 0.047 s | — | — |
| Stop request to TCP standstill | 0.156 s | 0.188 s | — | 0.234 s |

- **Typical chain:** about 0.20 s. **95th-percentile chain:** about 0.31 s. Both are inside the assumed T = 0.4 s.
- **The tail exceeds T:** the 99th-percentile sensing age plus the maximum tick plus maximum braking reaches about 0.44 s.
- **Not observable in these logs:** the latency inside the devices before streaming (MVN and Motive processing). It must be added from vendor figures.
- **Recommendation:** T = 0.5 s for the follow-up study, or report the residual risk of T = 0.4 s explicitly.

## 8. Phase recognition across the 12 participants

The deployed HMM was trained on three operators and never saw a participant, so every participant is a held-out test. Against the planned-cue phase labels it reaches:
- Accuracy: median 69% (range 44 to 80%).
- Balanced accuracy: median 65% (range 41 to 76%).
- By version: v1 median 69%, v2 median 69%. The lowest is P39/P42 (44%), the person recorded at about 26 Hz.

This is below the 79.4% reported for held-out operators. The labels mark planned cue windows rather than observed phase onsets, so these figures are a lower bound. The most common error is working → approaching (12,406 samples).

**Effect on the controller.** Phase affects only the yellow-zone speed cap. Stops come from the red boundary, the envelope and the trunk or limb predictor, so phase errors cost efficiency, not safety.

## 9. Questionnaires

Ratings came from 11 people over 31 blocks. The twelfth person completed only the intake, under both codes and with identical answers, which confirms P39 and P42 are one person. P15 and P22 lack block C. Every rating is linked to the controller that ran in that block.

- **No rating differs between controllers** (Friedman p 0.11 to 0.94 for all ten items). This covers confidence that the robot would stop, needing to watch it, "slowed more than it needed to", workload, and affect.
- **End of session:** "felt safest", "felt least safe" and "would pick for a shift" are spread at chance (binomial p ≥ 0.52). Only 4 of 11 noticed anything change between blocks.
- **Perception does not track measurement.** Within a person, "slowed more than it needed to" does not follow the measured unnecessary stopping in the same block (repeated-measures r = 0.17, p = 0.47). The measured differences of about 1 s/min are below what workers notice.
- **Order effect.** Feeling relaxed rises from the first to the third block, whatever the controller: means 3.78, 4.56, 4.67 (Friedman p = 0.011). This is habituation, which the counterbalanced order controls.
- **Overall:** felt safe and trust, median 4 of 5. The suit restricted movement little, median 2 of 5.

**Implication.** Within this range, choosing a controller costs nothing in perceived safety or workload. The case for the trunk-intent predictor is therefore objective: more margin against distance error and fewer unnecessary stops. It does not rest on preference.

## 10. Still to do

1. Optional: retrain the HMM leaving one participant out, to see whether participant data improves phase recognition.
2. Write the vendor device latency into the reaction-chain budget.
3. A confirmatory physical session with:
   - the trunk-intent predictor
   - T = 0.5 s
   - re-measured MVN profiles per person
   - a frozen version
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
python scripts/analyse_latency_and_phase.py   --captures <raw>/data/xsens
python scripts/analyse_questionnaire_links.py --qdir <private>/questionnaires \
       --trials <private>/counterfactual/counterfactual-per-trial.json
```
