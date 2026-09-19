# System architecture

The repository has three distinct execution paths. Choose the path before interpreting its outputs.

| Path | Entry point | Meaning |
|---|---|---|
| Helmet-body dashboard | [dashboard_server.py](../scripts/dashboard_server.py), `DashboardState._tick_locked` | OptiTrack head features, anchored Xsens body, live TCP, capture and task automation |
| Older live/bench runner | [live_run.py](../scripts/live_run.py) | In `--source fused`, records Xsens alongside OptiTrack; the head remains the controller input. It does not invoke `HelmetBodyTracker`. |
| Offline simulation | [run_simulation.py](../scripts/run_simulation.py) | Synthetic trajectories, separately seeded model fitting, controller comparison and ablations |

The name “fused” in an older command is not proof that it performs the later body transform.

## Dashboard: one observation tick

1. Xsens and OptiTrack receivers update their latest-sample stores independently.
2. The ticker reads the stores at a nominal 60 Hz. It obtains the current robot TCP from RTDE; a configured TCP is used only in the explicit no-rig model-development branch.
3. `HelmetBodyTracker.update` transforms Xsens segment poses using the optical helmet and the saved robot extrinsics.
4. `FeatureExtractor.push` derives head movement features from the optical head in robot coordinates.
5. Ready body features and geometry are attached to the feature frame. `FeatureFrame.as_vector` selects the recognition inputs; `FeatureFrame.for_control` selects the distance and motion used by controllers.
6. The active controller produces a requested speed fraction. Shadow controllers can evaluate the same observation for comparison. Output application is recorded separately from the decision.
7. Schema-v3 JSONL rows retain source inputs, derived features, decisions and robot telemetry. Task events and the final manifest provide trial context.

See [data fields and clocks](../data/README.md) before computing duration or aligning a second recording.

## Recognition and control use different observations

The committed pilot model has four inputs: head distance, projected closing velocity, speed and heading alignment. The legacy field `torso_facing` is the cosine of velocity heading relative to the direction toward the column, not a measured torso orientation.

For eligible dashboard observations, control can instead use the minimum of 23 anchored segment-origin distances, the maximum nonnegative segment closing speed, and the maximum segment speed. The nearest and fastest-closing origins may differ. These bounds are attached separately so adding body control does not silently change the meaning of the head-trained HMM.

A 12-input head/body model contract exists, but its implementation is not evidence that a body model has been fitted and validated. A body-trained model needs correctly labelled development data and independent evaluation.

**Mode details matter:** recording in `qualification` mode explicitly removes body geometry from the scored feature frame. Missing body evidence requests zero in the enabled, non-qualification recording path. An available body pose can still lack velocity during warm-up or after a source gap; a legacy head model can then retain head-only geometry. A body-input HMM additionally requires body geometry. Inspect `geometry_source`, body readiness and collection mode in each record rather than assuming every row used the same geometry.

## Three controllers

| Condition | Core rule in dashboard SSM mode |
|---|---|
| Fixed zone | Fixed distance zones select stop, reduced or full speed. |
| Reactive SSM | A distance/closing-speed envelope limits the requested speed, with the shared fixed-red stop. |
| Predictive SSM | The same envelope is combined with a phase-based cap and a separate kinematic intrusion predictor. |

The configured red radius is `K*T + C + Sa`. The dynamic threshold is `max(0, v_proj)*T + C + Sa`, followed by a linear speed ramp. With the saved defaults these are prototype parameters, not measured certification limits.

The predictive SSM command is bounded by the envelope for the same observation, parameters and mode. That inequality does not establish physical safety or an efficiency advantage. The fixed-red override applies in SSM; simulation also explores hand-guiding and monitored-stop branches. The dashboard calls the separation controllers with `robot_mode="ssm"`.

The three phase labels are approaching, working and retreating. Intrusion prediction is a separate channel based on distance and motion, not a fourth HMM phase. Online filtering uses only observations up to the current tick; an offline Viterbi score uses the complete sequence and must be reported separately.

## Body-driven task progress

[Simulated drilling](../src/hrc_safety/simulated_drilling.py) matches panel corners in the panel frame and checks hand proximity/dwell. The saved configuration uses a 0.12 m radius and 1.0 s dwell. A completed gesture represents task progress, not verified fastening. [Automation](../src/hrc_safety/automation.py) and the dashboard's `AutomaticRunController` manage the sequence and retreat conditions. Physical motion and suction routines are installation-specific.

## Source reading order

| Question | Source |
|---|---|
| What bytes and conventions arrive from the suit? | [xsens_transport.py](../src/hrc_safety/mocap/xsens_transport.py) |
| How does the dashboard receive optical poses? | [optitrack_transport.py](../src/hrc_safety/mocap/optitrack_transport.py), especially `NatNetV4Listener` |
| How are the frames combined? | [body_tracking.py](../src/hrc_safety/body_tracking.py) |
| How do recognition and control inputs differ? | [features.py](../src/hrc_safety/features.py) |
| How are commands calculated? | [controllers.py](../src/hrc_safety/controllers/controllers.py), [envelope.py](../src/hrc_safety/envelope.py), [horizon.py](../src/hrc_safety/horizon.py) |
| How is the model fitted and loaded? | [pilot_training.py](../src/hrc_safety/pilot_training.py), [pilot_model.py](../src/hrc_safety/pilot_model.py), [upper.py](../src/hrc_safety/lhmm/upper.py) |
| Where does live orchestration happen? | [dashboard_server.py](../scripts/dashboard_server.py) |
| Which software properties are tested? | [body tests](../tests/test_body_tracking.py), [core tests](../tests/test_core.py), [dashboard pipeline tests](../tests/test_dashboard_pipeline.py) |

The software is organised around testable numerical modules; the dashboard is the installation-specific orchestration layer. Start an independent tracking application with the parser and body tracker rather than copying the dashboard's robot-motion routes.
