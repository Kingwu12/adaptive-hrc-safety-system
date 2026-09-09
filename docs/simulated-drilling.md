# Simulated drilling detection

The task is a gesture rehearsal: no screws and no actual drilling. A completed
gesture means a hand remained close to a target, not that anything was fastened.

## Inputs and implementation

The live NatNet 4.0 multicast packets contain the named `PANEL` set with four
marker coordinates. The previous rigid-body parser skipped this block. The
additional parser now retains named sets in raw OptiTrack metres without
changing the existing head/robot rigid-body parser. Missing sets replace, rather
than retain, old data. The backend exposes marker sets and raw hand data through
`hand_tracking` status and records marker sets in trial JSONL.

Hand segments are 11 (right) and 15 (left). They are Xsens segment origins,
not fingertip measurements. See the [Xsens streaming specification](https://www.xsens.com/hubfs/Downloads/Manuals/MVN_real-time_network_streaming_protocol_specification.pdf)
and [Xsens user manual](https://www.xsens.com/hubfs/Downloads/Manuals/MVN_User_Manual.pdf).

The detector uses live marker coordinates, not hardcoded world corners. Either
hand may visit each marker in any order. The initial settings are 0.12 m proximity,
2 s continuous dwell and a maximum 0.15 s sample gap; physical suitability of
these settings has not been established. Switching hands resets that marker's
dwell. Cached samples cannot accumulate time. Both streams must advance and be
fresh. Clock reset or changed indexed marker geometry requires observer reset.
Progress resets for each trial. The four set indices must remain consistent;
symmetrical marker permutations cannot always be detected from geometry alone.

## Frame alignment still required

`simulated_drilling_alignment` in the application configuration must provide
`accepted: true`, `from_frame: xsens`, `to_frame: optitrack`, `units: m`, and
a measured proper 3x3 `rotation` plus three-component `translation`.
This records an already validated alignment; setting `accepted` does not measure
or validate one. The robot's OptiTrack transform is not an Xsens transform.

The only saved Xsens alignment found in `data/calib/xsens_points.yaml` is rejected
(0.205338 m RMS error). It is not used. No identity transform is assumed. MVN
resets, recalibration and drift can invalidate previously measured alignment.
Before detection can be relied on, aligned hand positions must be checked at the
four real targets, including the hand-origin offset and expected pose variation.

## Integration boundary

During the automatic qualification task stage, the backend records each completed
gesture as `simulated_drilling_marker_complete` and exposes `simulated_drilling`
progress. The dashboard labels this as a detection preview. It does not advance
the trial or command lowering: task confirmation remains explicit while the
alignment/detection is commissioned. Neither parser nor detector enables live
automation. No hardware service was restarted for this change.

Tests cover packet retention, truncation, malformed data, rigidly moving targets,
four distinct dwells, missing/stale/repeated samples, changing hands, frame resets,
geometry changes and the backend event/status path using fake hardware.
