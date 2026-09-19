# Data and artifact guide

This directory contains several different kinds of evidence. A filename beginning with P does not by itself establish a unique participant, a complete session, or inclusion in the final analysis.

## What is in the public checkout

| Path | Role |
|---|---|
| `xsens/` tracked historical files | Earlier development/bring-up captures and registry; not the complete final study dataset |
| `models/pilot_hmm.json` | Active historical head-feature model and stored validation metadata |
| `models/*candidate*.json` | Candidate artifacts; their presence does not mean promotion |
| `calib/`, `taught_poses.json` | Recorded installation-specific calibration/pose artifacts |
| `mocap/`, `verification/` | Historical capture/bench/qualification records; inspect each record's provenance |
| `logs/`, `analysis/metrics.json` | Synthetic simulation example decisions and metrics |

Do not relabel all tracked captures as synthetic fixtures. Development data and final participant evaluation are separate, and historical schemas differ.

The final study inventory, Forms export, participant-level analyses and new P/Q capture files are ignored by Git. Full-study inputs are kept in controlled storage; the [paper guide](../paper/README.md) describes the required paths. The public manuscript includes aggregate tables and figures. Native MVN/Motive recordings and participant videos are not created by the Python capture path.

## Dashboard schema-v3 records

Each JSONL line is one dashboard capture tick, not necessarily one new packet from each device. Selected fields in [`DashboardState._tick_locked`](../scripts/dashboard_server.py):

| Field | Meaning |
|---|---|
| `schema_version`, `capture_mode` | Record format and capture path |
| `participant_id`, `trial_id`, `session_id` | Recorded identifiers; reconcile session restarts before treating them as people |
| `controller_condition`, `block_label`, `collection_mode` | Actual condition and protocol context; block letters are not controller names |
| `xsens_frame` | Parsed MXTP02 metadata and raw segment positions/quaternions |
| `optitrack_rigid_bodies` | Raw optical poses, source values, receive ages and marker-fit error where present |
| `optitrack_marker_sets` | Named marker positions used by panel/task geometry |
| `geometry_reference`, `robot_telemetry` | TCP reference and robot state accompanying the calculation |
| `body_tracking` | Anchored segment poses, readiness, source pair, features and geometry |
| `features` | Head observation plus optional body features/geometry |
| `controller_decision`, `controller_comparison` | Active and shadow requests, geometry source and reasons |
| `controller_output_applied` | Whether output application was enabled; also inspect decision output status |
| `model_sha256`, `study_release_sha256` | Recorded model/release fingerprints where present |
| `ground_truth_phase`, `ground_truth_event` | Recorded labels/cues; event-label basis must be checked |

A planned cue is not measured event onset, and a zero requested speed is not independently observed robot immobility. Do not convert these fields into stronger ground-truth claims.

## Clocks and gaps

- `recorded_monotonic_s` is the capture machine's monotonic tick time. Use within-session differences for observed capture intervals; values are not comparable across machines or restarts.
- `recorded_utc_time` supports approximate wall-clock association. It is not a sensor synchronization guarantee.
- `t` is a bridge-relative pipeline time. The bridge enforces a nominal minimum tick increment when scheduling timestamps coincide; it can differ from measured wall-clock spacing.
- `xsens_frame.time_code_s` is the suit packet time code; sample counters support duplicate/reset detection.
- In the dashboard's NatNet receiver, optical `source_time_s` is derived from frame number / nominal 120 Hz. Its name does not make it a native capture timestamp.
- Receive-age fields describe local arrival freshness. Small age differences do not prove simultaneous capture.

Repeated source packets can appear in successive capture rows, and gaps mean the record is not an uninterrupted 60 Hz trace. Preserve missing intervals, check resets, and state how valid-duration denominators are calculated. [The empirical analysis](../scripts/analyse_recovered.py) and [independent verification](../scripts/verify_empirical_analysis.py) document the final paper's treatment.

The [older live runner](../scripts/live_run.py) uses a different schema with `pos` and optional sensor payloads. It is not interchangeable with dashboard rows or the `.npz` trace format consumed by [replay.py](../scripts/replay.py).

## Extending the dataset

Keep raw files immutable and record their hashes. Store derived outputs separately, document exclusions, and retain the collection mode and source revision. Use a clearly labelled synthetic dataset for public examples. Check the actual staged files before committing: ignore patterns do not remove data that was already tracked.
