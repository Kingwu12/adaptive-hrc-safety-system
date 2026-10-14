# Final presentation: rehearsal and rubric guide

Use **FYP-assessment-presentation-v2.pptx** for the assessment narrative. Earlier working drafts are superseded. The deck's speaker notes contain the talk track and sources. Rehearse from them rather than reading slides aloud.

The official ENG4702 presentation rubric supplied through the course specifies a general engineering audience, a strict **10-minute maximum**, and participation by every team member. It distinguishes this presentation from a paper summary. No fixed slide template is required; the revised deck retains the existing layout and typography.

## Running order

The planned talk is **9 minutes 15 seconds**, leaving 45 seconds for pauses and handovers. This is an allocation, not a completed timed rehearsal. Use a visible timer and follow the chair's instructions.

| Slide | Speaker | Seconds | Cumulative | Focus |
|---|---|---:|---|---|
| 1 | Zenan | 20 | 0:20 | Introduction |
| 2 | Zenan | 45 | 1:05 | Problem and beneficiaries |
| 3 | Zenan | 45 | 1:50 | Task and prototype |
| 4 | Zenan | 65 | 2:55 | Controller choices |
| 5 | Zenan | 55 | 3:50 | Design and measurements |
| 6 | Zenan | 40 | 4:30 | Recognition results |
| 7 | Zenan | 60 | 5:30 | Questionnaire findings |
| 8 | Michael | 55 | 6:25 | Distance measurement |
| 9 | Michael | 55 | 7:20 | Project management |
| 10 | Luke | 45 | 8:05 | Deployment constraints |
| 11 | Luke | 40 | 8:45 | Team contributions |
| 12 | Luke | 30 | 9:15 | Contribution and conclusion |

Prepared handovers:

- After slide 7, Zenan: “Michael will now explain what the measurements taught us and how we managed the experimental challenges.”
- After slide 9, Michael: “Luke will now relate those findings to deployment constraints and the team's contribution.”

All three members contributed to experiment design and final-report preparation. Their main areas were software development and technical integration (Zenan), communication and coordination with laboratory staff and supervisors (Luke), and physical setup and assembly support (Michael). AI assistance is disclosed consistently with the paper.

## Rubric coverage

| Criterion | Weight | Where addressed | Rehearsal requirement |
|---|---:|---|---|
| Individual contribution | 10% | Slide 11; three speaking sections | Each person explains their own work and speaks professionally |
| Terminology for non-experts | 10% | Slides 3–8 explain tracking, recognition and speed control | Explain terms rather than reciting acronyms |
| Relevance and significance | 10% | Slide 2: worker access, coordination and beneficiaries | Make the installation problem concrete |
| Design and conduct | 10% | Slides 3–5: apparatus, controller choices, rotated order and measures | Distinguish intended comparison from analysed evidence |
| Constraints and context | 10% | Slide 10: safety, cost, worker experience and environment | Explain why these factors affect deployment |
| Solution in context of the question | 10% | Slides 4, 6–8 and 12 connect choices and findings to coordination | State the supported answer without implying superiority |
| Project management | 10% | Slide 9: integration, changing geometry, variable cues and incomplete sessions | Explain a setback and the engineering response |
| Work volume and complexity | 4% | Slides 3–6, 9 and 11 show the integrated work streams | Explain how the components depended on one another |
| Logical sequence and timing | 4% | Problem → choices → evaluation → findings → context → conclusion | Complete a timed run below 10 minutes |
| Speaker transitions | 3% | Handovers after slides 7 and 9 | Rehearse names, clicker transfer and the next speaker's opening |
| Appropriate visuals | 4% | Schematic, editable charts and concise tables | Check readability on the assessment display |
| Clear, complete answers | 15% | Prepared questions below | Practise concise answers and expand when asked |
| **Total** | **100%** | | |

Content coverage is not a predicted mark. Delivery, individual understanding, timing and live answers must be demonstrated by the team.

## Prepared questions

**Did predictive control perform better?** The current analysis does not establish a safety or efficiency advantage. It demonstrates a physical prototype, development-stage recognition performance and descriptive experience findings. A stronger comparison needs validated clearance and stopping measurements and reliable controller exposure.

**Why three controllers?** They separate the information added at each stage: distance, closing speed, then task context and boundary prediction. Reactive control is the relevant comparator for the incremental value of prediction.

**How could prediction help if it only reduces speed?** At identical inputs it cannot request more speed than reactive control. Any benefit would need to come from intervention timing or subsequent coordination. We have not demonstrated that benefit here.

**What does 79.4% recognition accuracy mean?** It is the stored development-validation accuracy for assigning observations to approaching, working or retreating using present and past observations. Each of three operators was held out in turn. Equal weighting across phases gives 72.5%. Neither figure measures stopping safety or hazard detection.

**How many people were analysed?** The team reported 12 physical participants. The analysed records include 14 telemetry trials under three study IDs and 31 block forms under eleven IDs, with eleven matched intake/end response sets. Restarts prevent treating every ID as a verified distinct person. Record counts are not an independent participant sample size.

**What do the questionnaires establish?** Eight of eleven matched safety ratings were higher at the end than at intake; trust changes were more mixed. This compares expected with experienced ratings. It describes reported experience and cannot identify a controller effect.

**Were questionnaire findings sensitive to incomplete responses?** Restricting the block analysis to nine complete response sets preserved 29 of 30 block-item medians. The block-B monitoring median changed from two to one. Paired ratings still varied: unnecessary-stopping ratings rose in two sets, fell in two and stayed the same in five.

**Does the discrepancy mean someone was half a metre closer than believed?** No. It is a difference between the recorded head-distance calculation and a recalculation using recorded robot position. It is not a calibrated physical clearance error. Real protective clearance must cover the body, robot, tool and panel surfaces.

**Was this a certified safety function?** No. It was a laboratory research prototype using ordinary robot command interfaces. A bounded software request does not validate sensing uncertainty, the stopping chain or installed-system safety.

**What is new?** Adaptive speed control and task-aware safety already exist. The contribution is their integration and exploratory evaluation in a physical ceiling-panel task, using robot telemetry and questionnaire responses. Xiao Lin and colleagues' related 2026 study used a semantic workflow in a VR wall-panel task with simulated sensors; superiority over that approach is not claimed.

**How were setbacks managed?** Geometry versions were analysed separately, cued events were checked against recorded movement inputs, and incomplete or ambiguously linked observations were not used to support a statistical controller ranking. These decisions limit the conclusion while preserving its meaning.

**What would justify deployment?** Validated geometry for the complete moving volume, measured stopping response, a suitable safety chain, verified controller exposure, and evaluation with relevant workers and site conditions. Cost, energy and material effects need their own measurements.

## Media and setup

The timed deck is self-contained and uses a still schematic. It does not require video playback, internet access or participant recordings. No new 3D graphics were built. Any later video addition requires another timed rehearsal.

If participant footage is added later, select a short clip that explains the task, check the applicable consent and remove identifying material where appropriate. A schematic or unlinked illustrative clip must not be presented as a measured experimental result.

Before assessment, open the PPTX on the actual presentation machine and check charts, fonts and speaker notes. The deck was rendered and inspected with presentation tooling here; that is not a claim of a completed PowerPoint rehearsal.
