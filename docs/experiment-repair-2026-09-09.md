# Experiment review — 9 September 2026

Later update: the v5 automatic engine now supports participant and rehearsal
collection modes with identical physical checks. The Q-only capability statements
below describe the earlier repair. See [the current automatic-trial handoff](automatic-trial-qualification.md).
The historical data audit and model-validation findings below are unchanged.

## Decision

Preserve today's recordings as the original study version. Do not label the entire session final or discard it wholesale. Capture completion is different from valid event exposure and a valid controller comparison. Eligibility needs a documented trial-level audit, native recording verification, and independent event annotation. Do not silently relabel trials, choose exclusions from favourable outcomes, or pool later patched runs as if the implementation were unchanged.

The lab PC is off. These changes were prepared and tested on the home Windows PC; there has been no lab deployment or physical qualification.

## Evidence and coverage

The [session backup](https://drive.google.com/drive/folders/1i0ZDM7Fo-7v54zKzmPisj9zSHoaLxRFd) reports 55 attempts: 50 completed and 5 aborted. The [inventory](https://drive.google.com/file/d/12VZAm96_bABi1yb1Pm734m9NftcMfLF6/view) records 36 good grades across attempts; completed trials include 3 review grades and 11 without a grade. Those grades primarily assess capture, labels, timing and tracking.

Native MVN, Motive and video files were not present in this backup. Their references are preserved. This does not establish that the originals are missing from the recording devices.

Raw audit coverage is ONLY P17 T05–T09: five complete JSONL/manifest/event sets recovered from P17 archive parts 002 and 003. Both downloaded parts matched the published SHA-256 checksums, and complete entries passed ZIP CRC verification. Part 001 could not be downloaded; this review makes no raw-data claims about earlier trials or the predictive block.

| Trial | Assigned condition / event | Minimum distance in cue window | Maximum closing speed in cue window | Finding |
|---|---|---:|---:|---|
| P17 T05 | Fixed / distractor | 1.875 m | 0.302 m/s | No threshold mismatch detected by these checks; annotation still needed |
| P17 T06 | Fixed / clean | — | — | Measured motion present; annotation still needed |
| P17 T07 | Reactive / clean | — | — | Measured motion present; annotation still needed |
| P17 T08 | Reactive / distractor | 0.496 m | 1.494 m/s | Cue window entered the configured red boundary and included rapid closing |
| P17 T09 | Reactive / rapid intrusion | 2.034 m | 0.388 m/s | Cue window never reached the configured 0.6 m/s closing gate |

Distances are the system's recorded proxy, not independently certified body clearance. All five files contain fresh robot-motion telemetry. The diagnostic definition uses six valid joint velocities, source age at most 0.25 s, and maximum absolute joint speed above 0.005 rad/s; these are audit settings, not validated safety thresholds.

Recorded event labels identify planned cue windows, not independently observed event onset. The T08/T09 mismatch is evidence to investigate cue execution, timing, calibration and annotation; it is not sufficient to diagnose which of those caused it. Requested-stop durations include the full task and cannot be interpreted as false-stop rates or a controller ranking.

## Why the blocks feel similar

All three live controllers run in SSM mode and share the configured red stop radius (0.94 m at the saved defaults). The predictive controller is bounded by the reactive controller and can add caution; it does not grant an HMM-based exception to that common stop. Near-boundary stops can therefore be identical by design. A study expecting fewer near-person stops from the HMM is not testing a capability this implementation supplies.

The active historical HMM also has effectively locked transition priors because fitted frame-rate probabilities were raised to the eighth power. Training now preserves fitted counts by default. A candidate was fitted once to the existing 32 pilot trials from P03–P05, with participant-held-out validation; September 9 evaluation recordings were not used.

| Model | Offline accuracy | Causal online accuracy | Causal balanced accuracy |
|---|---:|---:|---:|
| Historical active model | 82.08% | 79.37% | 72.50% |
| Corrected training candidate | 76.21% | 74.41% | 68.54% |

The candidate is worse on these metrics and has NOT replaced the active model. It is a development artifact, not a validated improvement. Training now defaults to a separate candidate filename. The release gate requires participant-held-out causal accuracy of at least 0.80 in addition to its existing requirements; neither artifact currently passes that causal threshold.

## Changes prepared

- A Windows launcher starts the backend with automatic rehearsal and research-output flags, starts the dashboard, checks their connection, and reports missing dependencies or an incompatible existing service.
- Native-recording confirmation and trial start share one button, with duplicate-start protection. The launcher cannot start external MVN/Motive/video recordings.
- The active run displays the controller's requested output and reason. Independent shadow controllers log all three decisions from the same input; only the assigned controller commands output. These comparisons diagnose algorithms, not alternate physical outcomes.
- Automatic rehearsal displays event cues after telemetry reports movement. New exposure diagnostics flag absent rapid closing or intruding distractors and downgrade otherwise-good captures to review.
- New records identify cue labels honestly and store code/config/model fingerprints. A service refuses a new trial after relevant on-disk code or extrinsics change until restarted.
- Training rejects explicitly tagged participant-study, qualification, automatic and stale rows. Historical untagged pilot files remain supported; training inputs still require deliberate selection.

## Transfer to the lab

When the lab PC is on, finish any active work, check its checkout for local changes, and pull the verified commit without overwriting uncommitted lab work. In the repository, update the existing Python environment with `python -m pip install -e ".[dev,robot]"` using its `.venv\Scripts\python.exe`, and run `npm ci --include=dev` in `dashboard`.

Run `.\Start-Lab.ps1 -CheckOnly`, then `.\Start-Lab.ps1`. If a service was started without the required flags, stop that service deliberately after ending any trial and rerun the launcher.

Automatic mode remains limited to qualification rehearsals. Participant trials retain operator confirmations. The actual lab cycle, supported release, stop/resume behaviour, recording synchronisation and approved event routes still need witnessed qualification before participant automation can be released. Software tests here do not substitute for that evidence.

Before further comparative collection, verify that approved movement routes actually create the intended clean, distractor and intrusion exposures during robot motion, and determine whether the study hypothesis matches the implemented predictive controller. Improving model validation and demonstrating controller behaviour remain open work.

## Verification and reproduction

Python regression suite: 222 passed. Dashboard production build and lint passed. Local startup/proxy checks confirm automatic rehearsal enabled, no active automatic run, and no recording. No robot motion was requested during these checks.

Raw audit: `python scripts/audit_recorded_trials.py <recovered-directory> --output <audit.json>`. Defaults use the saved 0.94 m red boundary and 0.6 m/s closing gate; override explicitly for another configuration. The machine-readable audit reports scope and unresolved evidence for each file.

Candidate reproduction: `python scripts/train_pilot_hmm.py --participants P03,P04,P05 --validation participant --output data/models/pilot_hmm_candidate.json`.
