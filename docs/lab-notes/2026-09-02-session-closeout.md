# Lab session closeout — 2026-09-02

## Safe closeout state

- No guided recording was active.
- Robot was reachable in `RUNNING / NORMAL` with its program stopped.
- Arm joint position matched the taught low pose.
- VG10 suction was released on both channels and the pump was stopped.
- The local dashboard, Xsens listener, OptiTrack listener, and frontend development
  services were stopped after the checks above.
- No automatic robot power-down command was issued.

## Data and model snapshot

- 46 recording files were scanned by the training pipeline.
- 32 accepted study runs were used by the active two-component GMM-HMM:
  P03/King 8, P04/Mic 12, and P05/Luke 12.
- Leave-one-participant-out development estimate: accuracy 0.669, hazard precision
  0.490, and hazard recall 0.526.
- The model remains an experimental caution layer. Independent robot interlocks and
  the separation envelope remain the safety authority.

Post-closeout audit note: resetting Viterbi at unlabelled gaps revised accuracy to
0.670 while leaving hazard precision and recall at 0.490 and 0.526 (rounded). No
model parameter changed; only the validation sequence boundary was corrected.

## Archive policy

The project owner confirmed on 2026-09-02 that the approved ethics and participant
consent permit public distribution of the collected motion data. The raw recordings,
participant registry, calibration captures, derived analysis, and fitted model
artifacts are therefore included in the public GitHub repository. The local dashboard
authorization secret remains excluded. The complete source-plus-data ZIP is also
stored privately in the connected cloud account and retained locally for the project
team.

## Verified archive receipt

- Source snapshot tag: `lab-closeout-2026-09-02` (`5fd6ee7`)
- ZIP bytes: `64,778,807`
- SHA-256: `4628d648164c68f506e1ddc46e076c7a35e657602e83ae3aefb825669227d6f0`
- ZIP entries: 203, including 46 raw recording JSONL files and three model JSON files
- Private Google Drive copy: verified uploaded and `not shared`
- Empire artifact: `academic/eng4702/archives/adaptive-hrc-fyp-closeout-2026-09-02.zip` version 1, digest verified
- Excluded secret: `data/xsens/.control_key`
