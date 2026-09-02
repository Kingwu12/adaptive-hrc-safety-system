# Xsens full-body capture gap and correction — 2026-09-02

## Bottom line

The Xsens suit was streaming and the Mac recorded Xsens data, but the historical
Mac JSONL schema retained only segment 1 (pelvis) XYZ. The receiver parsed each
MXTP02 item only until it found the pelvis, then returned. It discarded the
pelvis quaternion and never persisted the remaining segment items.

This is a logger/receiver design failure. It is not evidence that MVN lacked
full-body estimates, and it is not accurate to say that today's runs contain no
Xsens data. The team confirmed after the run that native recording was never
started in MVN Analyze; MVN was used only as a live UDP source.

## What is present in today's Mac captures

Repository audit after the lab run found:

- 46 JSONL capture files and 361,987 rows in total;
- 43 files and 348,113 rows with a saved `xsens_position`;
- all 32 model-accepted runs, 214,187 of 214,187 rows, with saved Xsens pelvis
  XYZ; and
- zero saved segment collections and zero saved quaternions.

The fitted model still uses OptiTrack head-relative geometry. It did not train
on full-body Xsens kinematics, because those fields were not in the saved Mac
records or feature vector.

## Recovery status

Today's missing full-body data is **not recoverable**. There is no native MVN
recording on the Windows laptop, and the Mac did not retain the raw UDP packets.
The discarded segment positions and quaternions cannot be reconstructed from
the saved pelvis XYZ. Do not spend time searching for a Windows file or present
today's trials as full-body Xsens captures.

The three reported failed sensors (left foot, left shoulder and right upper
leg) still matter for future runs. A future native MVN export may contain
biomechanical estimates for those segments, but it must be described as
degraded capture and cannot support strong direct-measurement claims for those
limbs.

## Correction now in the acquisition path

Schema version 3 stores an `xsens_frame` on every recording tick. It contains:

- MXTP02 sample, datagram and avatar counters;
- MVN time code and local receive time;
- declared item/body/prop/finger counts; and
- every received segment's XYZ position and WXYZ quaternion.

The existing pelvis XYZ fields remain for replay compatibility. The parser now
builds the complete packet first; the pelvis-only interface selects from that
complete representation instead of creating a second lossy path.

The dashboard displays the received body-segment count and refuses to begin a
session below 23 segments. It also requires a calibration mark less than five
minutes old and the visible filename/path of the native Windows MVN recording.
That reference and the active model digest are written into every schema-v3 row.
The standalone recorder refuses to write incomplete frames. A recorded
`live_run.py` run fails closed if the Xsens packet contains fewer than 23 body
segments.

## Mandatory preflight before the next participant

1. Start MVN Position + Quaternion streaming and confirm the dashboard reads
   `Xsens 23/23 segments` at approximately 60 Hz.
2. Record a disposable five-second test.
3. Run `python scripts/verify_xsens_capture.py <preflight.jsonl>` and require
   `XSENS CAPTURE PASS`.
4. Inspect one JSONL row: `schema_version` must be 3; `xsens_frame.segments`
   must contain keys 1 through 23; each must contain three `position_m` values
   and four `quaternion_wxyz` values.
5. Confirm `sample_counter` and `time_code_s` advance across rows.
6. Start and stop a disposable native recording in MVN Analyze, then verify the
   native file exists before enrolling the participant. This is the master
   source for MVN outputs not carried by the MXTP02 pose stream.
7. Stop if any condition fails. Do not discover capture completeness after the
   participant leaves.

After the ten planned pre-study guided runs, run the batch gate:

```bash
python scripts/verify_xsens_capture.py data/xsens/P06-T*.jsonl \
  --trial-batch --min-captures 10 \
  --report data/verification/prestudy-xsens-batch.json
```

This additionally requires unique session and native-MVN references, one
unchanged real model digest, all three phase labels, a hazard-event window,
less than five percent stale OptiTrack rows, advancing Xsens counters and actual
pelvis motion. A passing Mac report does not prove that the referenced Windows
files exist; the operator must verify those files on Windows before leaving.

[Movella's current MVN user manual](https://www.movella.com/hubfs/Downloads/Manuals/MVN_User_Manual_2025.0.pdf)
defines Position + Orientation (Quaternion) as the position and quaternion
orientation of each body segment, and defines a full-body model as 23 segments.
It also distinguishes segment pose from other available outputs such as tracker
kinematics, joint angles and centre of mass. The native MVN recording is
therefore deliberately retained alongside the Mac pose log.
