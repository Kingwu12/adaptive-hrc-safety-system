# Participant form access verification — 2026-09-03

## Result

The intake, block-feedback and end-survey forms are published to **Anyone with
the link**. On 2026-09-03 each exact responder URL was re-probed without a signed-in
Google session and returned HTTP `200`. The dashboard API independently reported
`accessible_without_login: true` for all three forms.

No Monash or Google login is required to open the participant questionnaire.

## Affected responder forms

- intake: `1FAIpQLSce3ywyZ9OFginm-8-Kk2GqH5rSl4UxfDqiieAg5iomivF3xA`;
- block feedback: `1FAIpQLSeKgkIe5wdqEuFGnOuGxPpqD8ssQdSAR09oxrnwEQyzCPJviA`; and
- end survey: `1FAIpQLSd4gfX2ljOfRFxyeYq2B-haGNhENzA6dCjnmhYTIXGpVxc87g`.

## End-to-end submission test

At 19:02–19:03 AEST on 2026-09-03, all three responder pages accepted a
clearly marked `TEST-LINK-20260903` response and showed their intended
confirmation message. The linked Google Sheet `Participant tracker` then
contained the same join key in:

- `Intake responses`, row 3;
- `Block responses`, row 5, with blinded block `A`; and
- `End responses`, row 3.

These rows are qualification data only and must be excluded before analysis.
The remaining physical witness is to scan the dashboard QR on the actual
participant phone during the ten-run qualification rehearsal; the public-link
probe and response-destination path are already verified.

The dashboard server checks public responder access every minute. Any future
`401` or `403` blocks QR verification and instructs the operator to restore
**Anyone with the link** access.
