# Pilot model improvement — 2026-09-02

## Problem found

The original four-state HMM used one diagonal Gaussian per state over
`[d, v_proj, v_lat_frac, a_proj]`. In the 23 accepted P03/P04/P05 runs, the
hazard-labelled interval contains both the simulated lunge toward the robot and
the immediate recovery movement away from it. Those opposing velocities average
to `v_proj = -0.029 m/s`, making the fitted hazard centroid look stationary and
overlap heavily with working.

## Change selected

The live observation is now `[d, v_proj, speed, a_proj]`, and every activity state
uses a two-component diagonal Gaussian mixture inside the same interpretable
four-state HMM. This represents the in/out motion modes without changing the
reported activity labels or allowing the learned layer to override the independent
separation envelope.

Participant-held-out development results on the same 23 runs:

| Model | Accuracy | Hazard precision | Hazard recall |
|---|---:|---:|---:|
| Original single-Gaussian HMM | 0.649 | 0.434 | 0.428 |
| Selected two-component GMM-HMM | 0.673 | 0.485 | 0.564 |

Hazard recall for held-out P03 (King), previously the weakest fold, increased from
0.249 to 0.509. The selected model improved all three aggregate metrics, but these
folds were also used to compare candidate configurations. They are therefore a
development estimate, not a final unbiased test result. The next recruited person
must be kept completely out of training and used once as the untouched test set.

## Capture change for future runs

The guided dashboard now tells the experimenter to press the hazard button at the
same instant as the verbal cue and to end the hazard label the instant the approved
motion ends. This reduces stationary reaction-time padding around the event.

The model remains an experimental caution layer. Robot motion interlocks and the
certified separation envelope remain independent of its prediction.

## Retraining after additional P05 runs

Nine further P05 (Luke) runs, T04–T12, passed the dashboard capture checks with a
GOOD score of 100. The active local model was retrained on 32 accepted runs:

- P03 (King): 8
- P04 (Mic): 12
- P05 (Luke): 12

The updated leave-one-participant-out development estimate is 0.669 accuracy,
0.490 hazard precision, and 0.526 hazard recall. This replaces the local 23-run
artifact because it uses all accepted recordings and removes the severe P05 run
imbalance. The small metric movement is not a like-for-like test comparison: the
held-out P05 evaluation fold increased from 3 to 12 runs. P03 hazard recall rose
from 0.509 to 0.534. A new untouched participant is still required for the final
unbiased evaluation.
