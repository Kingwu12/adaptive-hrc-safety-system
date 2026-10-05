# Response to Yizhe Wang's comments (received 5 Oct 2026)

Yizhe annotated an earlier draft ("HRC_FYP_Final_Paper_Draft_1", built 27 Sep). The changes below are applied to the current main manuscript (v3.1 base), which still contained most of the passages he highlighted. The paper is still 10 pages.

| # | Comment | Change in `paper/main.tex` |
|---|---|---|
| 1 | Add a schematic of the application scenario in the Introduction, and a zone schematic (red/yellow, as in Karagiannis et al. 2022, Figs 1–2) | New Fig. 1 (full width): (a) the existing lab photo, (b) a side-view schematic showing approach, work and retreat, the column stand-in under the TCP and how *d* is measured, (c) a to-scale plan view of the fixed controller's zones: stop inside 0.94 m, 35% speed inside 1.50 m, full speed outside. The fixed-controller text now gives these levels and the 0.05 m exit hysteresis. |
| 2 | Panel installation does not necessarily need a worker *and* a robot; start broader | The abstract and Introduction now open with panel installation as overhead work, then introduce the worker–robot arrangement as the one adopted in this study. |
| 3 | "The recovered study records contain" → clearer wording | Abstract: "The final analysed dataset contained 97 robot-data trials…" |
| 4 | "Reactive separation envelope" is too specific for the abstract | Abstract: "…faster than the speed limit set by the distance-based reactive controller." |
| 5 | Related Work has too much design rationale | The task-phase vs hazard argument moved to Section III-D. Related Work keeps one bridging sentence. |
| 6 | "position and velocity of the worker relative to the robot" is ambiguous | Section III-A now reads: the head's position relative to the robot, and the head's velocity in the room frame. Section III-C adds that *v* is a five-sample least-squares slope and that robot motion is not subtracted. |
| 7 | How is the vertical column proxy defined? | Section III-C: a vertical line segment with no radius through the horizontal position of a robot reference point, from the robot-base plane (z = 0) up to that point's height, in the robot-base frame. **q** is the point on it at the head's height, limited to that range. Shown in Fig. 1b. |
| 8 | Study IDs and record counts belong in Experimental Method | Study-ID notation and the 52/45 record split moved to Section V-B. Section III keeps only the description of the two system versions. |
| 9 | Add (a), (b), (c) under the apparatus subplots | Labels added under each photo (now Fig. 3). |
| 10 | Basis for the ±4 m/s² acceleration cap | Section III-D gives the actual basis. The acceleration is a three-sample slope of closing speed, which read about ±30 m/s² unclamped during development, so it is capped at about 0.4 g. The cap and the 0.6 m/s gate are stated as engineering noise-suppression settings chosen in simulation, not measured or standard values. In the later version the control input uses zero acceleration, so the cap had no effect there. The trigger description is also corrected: the real condition is a risk threshold equivalent to τ ≲ 0.58 s, with closing speed ≥ 0.6 m/s held for two samples (the draft said "0 < τ < 0.5 s"). |
| 11 | "Most restrictive state" is undefined | Section III-E: if head, body or robot-position data are missing or too old (over 150 ms for OptiTrack, over 0.25 s for the robot position), every controller requests a stop (u_cmd = 0) before its own rules run. Results now say "395 triggered the tracking-loss stop request". |
| 12 | How were the ground-truth phase labels generated? | Section IV: labels were recorded live. The experimenter pressed a key at each phase change to advance the dashboard's fixed task sequence, and each frame was stamped with the current phase. Phase-boundary criteria are given; robot-motion and hazard frames are excluded. All 32 trials follow the scripted order. The text also states that labels were not reviewed afterwards or double-labelled. |
| 13 | Are the per-class recalls offline or causal? Report causal | They were offline (Viterbi). Causal recalls were computed: approaching 0.684, working 0.905, retreating 0.586 (offline 0.693 / 0.923 / 0.654). Table III shows both, and Section IV discusses them. `scripts/phase_recall_by_decoder.py` reruns the stored leave-one-operator-out validation and writes `data/models/pilot_hmm_phase_recall.json` only if every stored value is reproduced. The model file is unchanged. |
| 14 | Define what participants did in clean / distractor / rapid trials | Section V-A, from the participant session pack. All three differ only during the lift, while the participant waits at the start marker. Clean: no cue. Distractor: on "now", one brisk sideways movement that does not close on the robot, then return. Rapid: one brief move toward the robot along a marked direction, then return at once; not a fall, trip or lunge. Both were demonstrated and practised first. |
| 15 | Were video, timestamps or session logs available to recover participant linkage? | Question answered below. The main-branch text is unchanged. |
| 16 | Explain the early proxy vs later live-reference geometry | Section III-C and Results VI-B. In the earlier version the column was fixed on the robot base's vertical axis (2.2 m high) and did not follow the arm. In the later version it follows the live TCP. The 0.481 m early discrepancy is the gap between those two columns, and it grows as the arm carries the panel away from the base axis. |

## Answer to comment 15 (participant linkage)

Partly, yes, though not through video.

- **Used:** the follow-up publication analysis (`docs/publication-analysis-2026-10.md`, branch `paper-v3.2`) linked study IDs to people using:
  - session timing: each analysed code is one continuous 25–35 minute sitting;
  - OptiTrack helmet height, which is independent of the Xsens body profile reused between people;
  - Xsens body-model segment lengths;
  - matching intake answers.
- **Concluded:**
  - 12 people in total.
  - P39 and P42 are the same person.
  - P13/P17 and P32/P35, the closest pairs by height, were confirmed as different people by the team on 3 Oct.
- **Not used:**
  - Session video exists (Fig. 1a is a frame from it) but was not reviewed for linkage.
  - No booking list or operator notes are in the repository.
  - The participant registry has no names for the study codes.
  - Native MVN/Motive files were not kept.
- **Unresolved:** who the short P23/P24 recordings (10 Sep) belong to.

These findings are written up in the internal v3.2 draft. They are not yet in the main manuscript, which still treats the 11 analysed codes as unconfirmed individuals.

## Points found while answering, for the team

- Because of the fixed column, early-version (P13–P22) distances, including the "stop requested whenever inside the red boundary" indicator, are relative to the controller's distance input, not the true head-to-panel clearance. The revised Results text says so.
- The ±4 m/s², 0.6 m/s and 0.5 s settings have no measured basis or citation. If an assessor asks, the honest answer is the one now in Section III-D.
