# Ethics and protocol reconciliation delta

**Prepared:** 2026-09-03
**Project:** MUHREC Project 51642
**Status:** unresolved collection gate; supervisor/MUHREC determination required before reported moving-participant collection.

## Approved-document witness

The available MUHREC approval correspondence lists these approved participant-facing documents:

- `explanatory_statement.pdf`, version 3.0, 27 April 2026;
- `Consent Form.pdf`, version 3.0, 27 April 2026; and
- `Simple_Post_Interaction_Survey.pdf`, version 1, 3 April 2026.

The available explanatory statement describes a controlled laboratory interaction with a robotic system or arm, simple guided tasks, feedback, a 30–60 minute session, and collection without identifying information. The available consent form covers robotic-arm interaction, guided tasks, feedback, observational data, thesis/future aggregate research and an explicit video-recording choice.

This record does **not** prove approval for every detail of the current implementation. The approved simple post-interaction survey has not yet been matched to the current intake, per-block and final Google Forms.

## Current implementation additions that require determination

Before collection, obtain a written supervisor/MUHREC determination on whether the existing approval covers each item below or whether an amendment is required:

1. a full-body Xsens wearable suit and retained native MVN recordings;
2. OptiTrack head rigid-body position/orientation and retained Motive takes;
3. synchronized robot telemetry, event logs and derived head-direction measures;
4. a pre-briefed rapid-intrusion event toward a validated protected volume;
5. the clean, distractor and rapid-intrusion within-participant schedule;
6. three blinded controller conditions across nine trials;
7. the current intake, per-block and final Google Forms;
8. storage, retention, access, de-identification and future-use wording for all raw files;
9. the exact video framing and the use of video to validate head direction; and
10. the participant name/signature fields in the consent form versus the statement that no identifying information is collected.

## Required reconciliation action

Provide the approver with:

- the current participant measurement plan;
- the machine-readable analysis plan;
- screenshots or exports of all three live Google Forms;
- the exact participant script and rapid-intrusion/distractor wording;
- a data-flow diagram listing Xsens, OptiTrack, robot, video, dashboard and Sheet files; and
- this delta.

Record the response as dated evidence. If an amendment is required, do not collect reported data under the expanded protocol until approval is received. If the approver restricts the study to stationary-arm sensing or removes an event/instrument, update the protocol, dashboard, analysis plan and frozen release together before collection.

## Gate closure evidence

The `protocol_and_ethics_reconciled` gate can turn green only when the repository contains:

- the dated written determination or approval reference;
- hashes or immutable copies of the exact approved participant-facing instruments;
- a signed-off protocol/version mapping showing no unresolved delta; and
- a dashboard/form readback demonstrating that the approved versions are the versions participants receive.

Until then, the gate remains red by design.
