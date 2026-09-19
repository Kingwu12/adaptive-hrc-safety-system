# Documentation guide

Read the learning guides first. Operational documents describe specific lab workflows; dated records preserve what was known at the time and may contain superseded commands or assumptions.

## Learn the system

1. [Xsens + OptiTrack integration](helmet-xsens-integration.md): frames, packets, timing, a worked transform and a hardware-free demonstration.
2. [Architecture](architecture.md): dashboard data flow, control versus recognition, and source-code reading order.
3. [Reproducibility](reproducibility.md): what a public checkout can reproduce and which analyses need private inputs.
4. [Data guide](../data/README.md): schemas, clocks, model artifacts and provenance.
5. [Contribution guide](../CONTRIBUTING.md): testing and extending the project without changing the meaning of historical data.

## Research and review

| Document | Purpose |
|---|---|
| [Paper and build instructions](../paper/README.md) | Canonical manuscript, analysis inputs and validation |
| [Final review](final-review.md) | Team review links and responsibilities |
| [Assessor preparation](assessor-preparation.md) | Research question, findings, equations and likely questions |
| [Presentation guide](../presentation/FYP-presentation-guide.md) | Speaking order, timing and rubric coverage |

## Lab operation

| Document | Purpose |
|---|---|
| [Windows lab handoff](windows-lab-2026-09-16.md) | Installation and launchers for the recorded Windows configuration |
| [Windows startup repair](windows-startup-repair.md) | Environment and startup diagnosis |
| [Automatic-trial qualification](automatic-trial-qualification.md) | Sequence, fault behaviour and checks |
| [Automatic data capture](automatic-data-capture.md) | Trial files and capture lifecycle |
| [Team experiment guide](team-experiment-guide.md) | Operator workflow and experiment terminology |
| [Participant session pack](participant-session-pack.md) | Participant and operator wording |
| [Participant measurement plan](participant-measurement-plan.md) | Intended measurement and questionnaire protocol |

A planned protocol is not evidence that every historical run completed that protocol. For what was analysed, use the paper and the recorded trial metadata. For what a program does now, follow the source links in the learning guides.

## Historical design and lab records

The [design folder](design/) contains proposals and architecture decisions. The [lab notes](lab-notes/) and [session records](session-records/) preserve dated observations. The [9 September system audit](system-audit-and-technical-guide.md) documents that revision's findings and tests; its deployment status is historical.

The [original OptiTrack bridge design](design/optitrack-bridge.md) describes a single-point bridge. The later [dual-stream bring-up note](lab-notes/optitrack-xsens-bringup.md) concerns the older `live_run.py` path. Neither replaces the current helmet-body tutorial. Early notes that say “Xsens, not OptiTrack”, describe a torso-only marker, or refer to synthetic paper placeholders record earlier project stages.

Files remain at their original paths so old links and experiment records remain interpretable. Start new work from the guides above, then consult the dated records for a specific question.
