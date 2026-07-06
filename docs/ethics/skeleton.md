# Ethics Application Skeleton — Adaptive HRC Safety Study

**Status:** DRAFT skeleton for MUHREC submission. Not yet reviewed. Fill bracketed
fields with the final lab setup and personnel before submission. Companion to
`docs/memo-yizhe-sem2.md` and `docs/experiment_plan.md`.

> **Timeline note.** MUHREC review is realistically **4–8 weeks**. This protocol must
> cover, in a single submission, all of: cued slips, cued distractors, video recording
> for labelling, and consent for an anonymised open dataset — so a second review cycle
> is not needed. Submit against the full protocol.

---

## 1. Study summary

We compare fixed-zone and adaptive robot safety logic during a simulated overhead panel
installation. A UR10e holds a lightweight surrogate panel while a participant performs an
alignment-and-fastening task beneath it. We measure how each safety controller trades off
**productivity** (robot speed while the participant works safely) against **hazard
response** (how it reacts when the participant approaches the robot). The scientific
question is whether context-aware logic reduces unnecessary slowdowns **without**
weakening the protective stop.

## 2. Participant tasks

- Repeated **Multi-Point Alignment & Tool-Retrieval loop**: retrieve a tool from a bench,
  approach the work face, align and "fasten" at two–three stances (surrogate fasteners),
  retreat to the bench, repeat.
- Two safety-controller conditions (fixed-zone vs. adaptive), order counterbalanced. The
  participant is **not told** which condition is active.
- Duration: [~X] minutes of active task per participant, plus briefing and questionnaires.

## 3. Cued-event protocol

- **Cued slips.** At **randomised** times an experimenter cues the participant (via a
  pre-agreed signal) to perform a **deliberate near-approach** toward the robot column —
  the simulated "slip." The cue timestamp is the exact **hazard-onset ground truth** used
  for response-latency scoring. Slips are **experimenter-cued, never participant-improvised**,
  so every hazard has a clean, fairly-scored onset.
- **Cued distractors.** Also at randomised times, the experimenter cues **fast but safe**
  motions — a fast lateral dart across the work face, or a sudden fast retreat. These are
  ground-truth **non-hazard** and test whether the controller over-reacts to movement.
- **Robot state during early pilots.** In early pilots the robot is held in
  **stationary hold**, so a cued slip approaches a *stationary* arm — the lowest-risk way
  to exercise the protective stop before any moving-robot trials.

## 4. Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| Contact / pinch with the robot or panel | Lightweight **surrogate** panel (not a real ceiling panel); robot in stationary hold during early pilots; **red-zone protective stop active in BOTH conditions**. |
| Protective stop fails | Hardware **e-stop** within the participant's and experimenter's reach at all times; continuous **supervision** by a trained experimenter. |
| Participant improvises an unsafe motion | All hazard/distractor events are **experimenter-cued**; participants are briefed to move only as cued. |
| Fatigue / strain from overhead task | Bounded session length; rest breaks; surrogate panel is light. |
| Startle from an unexpected robot stop | Participants briefed in advance that **the robot will stop** near them; no condition is less safe than the other. |

## 5. Data collected

- **Motion capture** (OptiTrack) of the participant's tracked points — the primary
  measurement.
- **Video** — for offline labelling of operator state (approaching / working /
  retreating / hazard) and distractor/slip windows. Faces [blurred / not recorded — decide].
- **Questionnaires** — perceived safety, comfort, and trust per condition.
- **Robot decision logs** — per-tick controller records (no personal data).

## 6. Consent items

- Participation is **voluntary**; the participant may **withdraw at any time** without
  penalty, and may request their data be destroyed up to [withdrawal cutoff date].
- Consent to **video recording** for research labelling.
- **Separate, explicit** consent to publication of an **anonymised open motion dataset**
  (motion-capture trajectories + labels, no video, no identifying information). This
  consent is **optional** — a participant may take part without agreeing to open-dataset
  publication.
- Consent to storage and handling of data per Monash data-management policy.

## 7. Withdrawal and data handling

- Withdrawal procedure and cutoff date stated on the consent form.
- Data stored on [Monash-approved storage]; access limited to the research team.
- Open-dataset release contains **only** anonymised motion + labels from participants who
  gave the separate open-dataset consent.

---

*Bracketed items and the participant-facing consent/explanatory statements are to be
completed on the final MUHREC forms.*
