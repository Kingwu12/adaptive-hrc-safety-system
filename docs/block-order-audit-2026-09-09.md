# Block-order and controller-identity audit — 9 September 2026

The saved assignment metadata changes across participants. Block labels A, B and C denote presentation position, so the labels themselves remain A → B → C.

| Participant | Block A | Block B | Block C |
|---|---|---|---|
| P06 | predictive SSM | not recorded | not recorded |
| P13 | fixed zone | reactive SSM | predictive SSM |
| P14 | fixed zone | predictive SSM | reactive SSM |
| P15 | reactive SSM | fixed zone | predictive SSM |
| P16 | reactive SSM | predictive SSM | fixed zone |
| P17 | predictive SSM | fixed zone | reactive SSM |

Source: [original trial inventory](https://drive.google.com/file/d/12VZAm96_bABi1yb1Pm734m9NftcMfLF6/view), fetched again for this audit. Assignment metadata establishes the recorded schedule; it does not by itself establish which controller executed. P06 contains only two block-A attempts in this backup.

## Executed-controller evidence available

Five complete raw P17 recordings were re-read independently of the assignment inventory:

| Trial | Block | Assigned controller | Decision identifier | Identified decisions / output-write confirmations |
|---|---|---|---|---:|
| T05 | B | fixed zone | static | 5,184 / 5,184 |
| T06 | B | fixed zone | static | 4,544 / 4,544 |
| T07 | C | reactive SSM | dynamic_ssm | 5,055 / 5,055 |
| T08 | C | reactive SSM | dynamic_ssm | 4,811 / 4,811 |
| T09 | C | reactive SSM | dynamic_ssm | 4,421 / 4,421 |

These records distinguish the controller producing decisions from its assigned label. Output-write confirmation is software evidence, not independent verification of physical response. Frames without an identity, including fail-closed tracking frames, are excluded from these counts.

This evidence contradicts an all-static execution explanation for these five recovered trials. It does not establish what every screen displayed or verify the unrecovered predictive block. The user's observation that all blocks displayed “static” remains unresolved as a display/source question.

## Dashboard changes

Operator details now show the assigned controller beside the identifier in the latest actual decision. A mismatch is displayed explicitly, and an absent identifier is shown as unavailable rather than guessed. The session map reveals the controller assigned to each A/B/C block for the selected participant. Operator-only disclosure remains collapsed so the participant briefing can keep neutral block labels.

The participant selector is disabled while recording or starting a run. Structured starts now require an explicit assigned slot instead of falling back to fixed-zone/A1 defaults. No evidence currently establishes that either of those previous UI paths caused today's observation.

The raw audit flags decision identities that disagree with assignment metadata. Regression checks exercise all three controllers through the recording service, including their persisted decision identifiers.

## Implication for today's data

The saved schedule does not support the claim that every participant received the same controller order. The original data remains unchanged. The exposure, native-recording, annotation and study-release questions from the earlier review remain open; this finding does not turn the dataset into an automatically approved final comparison.
