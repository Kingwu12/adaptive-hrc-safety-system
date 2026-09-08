# HRC Operator Motion Console

Local web interface for the Monash adaptive HRC safety FYP. The UI displays
the Xsens-derived position and motion features produced by
`scripts/dashboard_server.py`, captures participant/trial metadata, applies
ground-truth labels, and shows the current layered-HMM posterior.

The first screen is a hard three-way data-purpose choice:

- **Participant study** is the default Wednesday workflow. It creates anonymous
  study participants, assigns the nine frozen trials automatically, hides manual
  training controls, and tags every saved row `participant_study`.
- **Qualification** creates Q-coded mock operators and runs the exact nine-trial
  schedule and form handoffs without counting anything as a participant result.
  It tags every row `qualification`.
- **Model development** contains pilot operators, manual labels, model belief,
  sensor checks, and training captures. It tags new rows `model_development`.
  All older untagged files are treated as development data.

Never use qualification or development data as reported participant data. The permanent
row-level tag, rather than a filename convention or operator memory, is the data
firewall between model fitting and final evaluation.

## Run locally

Use Node.js 22.13 or newer. From the repository root, open two terminals:

```bash
python scripts/dashboard_server.py
```

```bash
cd dashboard
npm install
npm run dev
```

Open <http://localhost:3000>. Xsens Analyze/Animate and the Awinda USB driver
run on Windows 10/11, not macOS: attach the Awinda dongle to the Windows host,
then stream `Position + Quaternion` over UDP to this Mac on port `9763`.
The header must show `Xsens 23/23 segments` before recording. Also start a
native MVN recording on Windows; the Mac JSONL stores synchronized segment
poses, while the native file preserves the broader MVN data product.

The server logs fixed/reactive/predictive controller decisions for structured
runs. To qualify the experimental UR speed-slider output, deliberately launch:

```bash
python scripts/dashboard_server.py --enable-research-speed-output
```

That flag enables the research command path and records whether the UR controller
acknowledged each speed fraction. It is **not** a safety-rated stop function and
does not replace the independent safeguard, E-stop, supervisor witness, stop-time
test, or protected-geometry validation.

## Qualification workflow

Before a participant study, select **Qualification**, create `Q01`, and run the
same nine scheduled slots and dummy form handoffs. Then create `Q02`, start its
first assigned attempt, and use **Abort safely & preserve this attempt** to rehearse
recovery as the tenth batch capture.
Audit the resulting files with:

```bash
make qualification
```

The audit fails unless it finds at least nine completed trials covering all three
events and controllers, at least one controlled abort, unique MVN references,
full-body Xsens, fresh OptiTrack, real model hashes, controller decisions, and
acknowledged robot output.

## Wednesday participant workflow

For each new person, stay in **Participant study** and follow the single next-action
card:

1. Create the next anonymous participant code. Its prefilled Intake QR appears
   immediately before suit-up. With the completion bridge configured, the
   dashboard advances automatically when that participant ID reaches the response
   Sheet; otherwise use the visible confirmation-screen fallback.
2. Fit and calibrate Xsens; confirm `23/23`, fresh OptiTrack, trustworthy live TCP,
   and a recent calibration in the preflight list.
3. Begin a unique native MVN recording, enter its visible filename/path, confirm it,
   then start the assigned trial.
4. Follow the full-screen live run director. The dashboard automatically records
   the assigned block, controller, event, phase labels, telemetry, and collection
   mode. Physical robot or suction actions require a deliberate second press.
5. After saving, accept the slot only when its quality is GOOD. A failed attempt is
   preserved and the same assigned slot remains next.
6. After each three-trial block, show that block's QR and mark it submitted before
   the next block unlocks. Recalibrate before the next block. After Block C, show
   Block C feedback, then the Final QR and debrief.

Controller and event order are deterministic and counterbalanced from the participant
code. The operator does not manually choose them in Participant study mode.

## Participant phone flow

The operator selects the current participant and uses the **Participant phone**
panel. The participant scans one dashboard QR at each of five
moments only: intake once, feedback after each complete three-trial block (A,
B, and C), and the end survey once. The participant ID is prefilled. The block
letter remains a required participant-visible confirmation; controller identity
is never shown.

At the start of every lab day, scan each QR on the actual participant phone (or
a signed-out browser) and submit a Q-coded test response. Google Forms is the
phone interface; its linked Google Sheet stays the background response store and
analysis record.

For automatic form completion, deploy
`integrations/google_forms_completion_bridge.gs` from the Monash account. Set
the web app to execute as its owner and allow anyone with the URL, then save the
`/exec` URL in `data/xsens/.form_completion_url`. The dashboard server uses the
existing local control key as the private query token. The bridge returns only a
submission boolean; questionnaire answers stay in Google Sheets. If the bridge
is unavailable, the UI exposes one manual confirmation button rather than
blocking the session.

## Trusted lab-network viewing

```bash
python scripts/dashboard_server.py --share
cd dashboard && npm run dev -- --host 0.0.0.0
```

Teammates can use the Mac's LAN address to view the console. Remote browsers
are view-only unless the host deliberately adds `--allow-remote-control`.
Recorded JSONL data stays under `data/xsens/` and is ignored by Git.
