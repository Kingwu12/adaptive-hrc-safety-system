# Phase/event redesign after the 2026-09-02 pilot

## Decision

The upper GMM-HMM classifies three mutually exclusive task phases only:
`approaching`, `working`, and `retreating`. A rapid intrusion is an event that may
occur during any phase, so it is recorded separately and detected by the kinematic
time-to-breach layer. It is not a fourth HMM state.

The pilot capture field `torso_facing` was also corrected conceptually: it is the
cosine of velocity heading and the robot-closing direction, not a torso-orientation
measurement. The model artifact calls it `heading_alignment`. Acceleration remains
available to the independent event predictor but is excluded from phase recognition
because its pilot estimate is noisy.

## Frozen development model

- Data: 32 complete trials from P03, P04, and P05.
- Features: distance, closing velocity, speed, and heading alignment.
- Emissions: three diagonal Gaussian components per phase.
- Temporal model: transition counts fitted from training trials, raised to power 8
  and row-normalised to preserve a valid stochastic transition matrix.
- Validation: leave one participant out; Viterbi decoding resets at every invalid,
  unlabelled, or legacy hazard-labelled gap.

Results from `data/models/pilot_hmm.json`:

- Overall phase accuracy: **0.8208**.
- Balanced phase accuracy: **0.7567**.
- Immediate causal forward-filter accuracy: **0.7937**. The 0.8208 headline is
  offline Viterbi sequence decoding and must not be described as immediate live accuracy.
- Held-out participant accuracy: P03 **0.8116**, P04 **0.8173**, P05 **0.8324**.
- Phase recall: approaching **0.6933**, working **0.9229**, retreating **0.6539**.

This clears the 0.80 overall-accuracy target without counting hazard as a phase.
It does not mean every phase has 80% recall; class imbalance makes plain accuracy
look stronger than balanced accuracy.

## Claim boundary for the participant study

This is a development estimate, because the feature and transition design were
selected after inspecting these pilot folds. Freeze the model before the participant
study and use newly recruited participants as the untouched confirmation set. Do not
re-tune on their outcomes before reporting the pre-specified primary analysis.

Report the two endpoints separately:

1. Task-phase recognition: accuracy, balanced accuracy, confusion matrix, and recall
   for each of the three phases.
2. Rapid-intrusion response: event sensitivity, distractor specificity/false-stop
   rate, response latency, and minimum separation.

The deterministic red-zone and dynamic-envelope bounds remain independent from the
learned phase estimate. A phase-classification error may add caution but must never
permit a faster command than the envelope.
