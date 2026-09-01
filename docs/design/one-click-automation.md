# One-click panel-cycle automation

The automated experiment uses one deterministic task sequence for all three
conditions. The controller condition changes only the safety-supervisor output
(full speed, reduced speed, or stop), never the task poses or phase order.

```text
START -> LOAD -> TRANSIT_UP -> HAND_GUIDE -> HOLD_BOLT
      -> RELEASE_RETRACT -> COMPLETE
```

`PanelAutomation` in `src/hrc_safety/automation.py` owns this sequence. A live
adapter must provide head/Xsens/panel/base freshness, robot and emergency-chain
state, vacuum confirmation, panel-slip status, motion completion, and explicit
alignment/fastening confirmations. Any missing live interlock latches `FAULT`
and commands zero speed.

## Controller comparison

- Fixed zone: red stops, yellow reduces, green runs.
- Dynamic SSM: the measured closing speed controls the certified envelope.
- Adaptive: HMM/horizon risk may add caution but never exceed the envelope.
- Certified hand-guiding is a separate robot operating mode. Slow deliberate
  contact is permitted only there; an HMM belief alone never legalises an SSM
  red-zone breach.

## Physical run blockers

The real-arm start control must remain disabled until all are completed:

1. OptiTrack-to-UR-base transform accepted on an independent validation set.
2. TCP-to-panel transform calibrated; slip threshold measured.
3. VG10 telemetry accessible from Windows and grip threshold validated.
4. Waist/ceiling/retract poses reviewed on the pendant at reduced speed.
5. Physical emergency stop and safety-rated protective input validated.
6. End-to-end reaction/stopping time measured and written to configuration.
7. Tracking-loss tests pass with the arm in a safe reduced-speed trial.
8. Formal pilot HMM fitted from labelled real trials, not synthetic data.

Dashboard pause and RTDE speed-slider control are research orchestration, not a
safety-rated protective device. A real participant trial retains the robot's
certified safety configuration and physical stop chain.
