# Final presentation: rehearsal and rubric guide

**Thursday 29 October 2026, 2:00 pm.** Use **FYP-assessment-presentation-v4.pptx**. It is rebuilt by `python3 presentation/build_v4.py` from v3, which stays in the folder as the previous version. The speaker notes hold the full script for each slide. Rehearse from them until you can say each slide in your own words; reading from the slides is a fail item in the rubric.

v4 replaces v3 for two reasons:

1. **The rubric changed.** On 6 Oct 2026 the Chief Examiner (Tian Goh) rolled the presentation rubric back to a simpler version: four categories instead of twelve (below).
2. **v3 showed the old results.** It reported the 14-trial analysis ("does not yet establish a safety advantage"). The paper (v3.2) now has all 12 participants and the same-input replay, so the slides now say what the paper says.

## Running order

Target **9:30**. The scripts are about 1,130 words; the slide timings below assume 130 words a minute and add up to 8:40. Pauses and two handovers usually add 30 to 45 seconds. That leaves about 30 seconds before the hard 10-minute stop. The rubric's top band asks for "exactly to time", so set a timer you can see and practise until a full run lands between 9:15 and 9:45.

| Slide | Speaker | Time | Ends at | Focus |
|---|---|---:|---:|---|
| 1 Title | Zenan | 0:30 | 0:30 | Who we are, roadmap |
| 2 Why this problem matters | Zenan | 0:50 | 1:20 | Why care, who benefits |
| 3 Our solution | Zenan | 1:15 | 2:35 | Three controllers, slow-only rule, why we chose them |
| 4 How we tested it | Zenan | 0:45 | 3:20 | 12 people, rotated blocks, same-input replay |
| 5 The test rig | Michael | 0:40 | 4:00 | Physical setup (Michael's contribution) |
| 6 Result 1: safety | Michael | 0:50 | 4:50 | 970/970, earlier stop, margin under distance error |
| 7 Result 2: the cost | Michael | 0:45 | 5:35 | Brief extra stops, unnoticed, robot stopping time |
| 8 The task is the limit | Michael | 0:45 | 6:20 | A third of each trial stopped; contact-safe mode next |
| 9 Project management | Luke | 0:55 | 7:15 | Plan, setbacks, responses (Luke's contribution) |
| 10 Using it on site | Luke | 0:50 | 8:05 | Safety, cost, health, carbon, people, standards |
| 11 Answer and next steps | Luke | 0:35 | 8:40 | Answer to the question, next steps, why pick this topic |

These are allocations, not a timed rehearsal. Time a real run before trusting them.

Speaking time: Zenan 3:20, Michael 3:00, Luke 2:20. Each person opens their section with what they personally did. If the team wants Luke's share closer to the others, Luke can take slide 8, which leads naturally into his section.

**Prepared handovers** (also at the end of the notes on slides 4 and 8):

- End of slide 4, Zenan: "Michael will now show you the rig we tested on and what we found."
- End of slide 8, Michael: "Luke will now explain how we managed the project and what it would take to use this on a real site."

Pass the clicker with the last sentence, not after it.

## Before Thursday: things only the team can fill in

- **Michael, slide 5 notes:** replace the bracketed line with one or two concrete things you set up or assembled.
- **Luke, slide 9:** check the month-by-month plan (Jul design and simulation, Aug rig integration and pilot tests, Sep sessions, Oct analysis and paper) against what actually happened, and correct it in `build_v4.py` if needed.
- **Everyone:** open the deck on the presentation machine, check fonts and charts, and do two timed full runs.

## Rubric coverage (rolled-back rubric, 6 Oct 2026)

| Category | Weight | Where it is covered |
|---|---:|---|
| Individual contribution (per student) | 10% | Each speaker opens with their own role (slides 3, 5, 9); roles repeated on slide 11. Speak, don't read; dress for a business setting; no filler words. |
| Technical elements, constraints and contextual factors, adaptability | 60% | Why care and who benefits (2); solution chosen and justified (3); design and conduct for a general audience (4, 5); honest results including the flaw we found (6, 7, 8); project management with setbacks (9); safety, whole-life cost, health, net zero carbon and social factors (10); answer to the research question and why another student should pick this topic (11). |
| Structural and visual elements | 15% | Problem, solution, test, results, management, context, answer. Photos, native charts, diagrams; text kept short. Two prepared handovers. Target 9:30. |
| Responsive elements (answers to questions) | 15% | Prepared answers below. Keep each to two or three sentences, then stop. |

Points the old guide covered that the new rubric now stresses:

- "The presentation should not be a summary of your paper." v4 leads with why it matters, the choices we made and what it would take to use on site, not the paper's section order.
- "Could have convinced other students to choose this topic." Luke's closing line on slide 11 does this.
- "Questions about problems or adversity were answered honestly and constructively." See the setback questions below.

## Prepared questions

Answer in two or three sentences, then stop. Offer more detail only if asked.

**Is your controller safer than fixed zones?**
On the measured distance, all three controllers had already asked the robot to stop at every one of 970 entries, so they were equally safe there. Ours asked about a tenth of a second earlier for all 12 people, and that earlier request gives more margin when the distance is measured wrongly: 67% of entries still covered with a 5 cm error, against 31% for fixed zones.

**Then why does the robot stop more with your controller?**
The intrusion predictor releases the stop as soon as the risk dips, so a noisy speed estimate makes it flicker between stop and go. That added under a second of unnecessary stopping per minute, and participants did not notice it. A short release delay should remove most of it.

**What is same-input replay, and why trust it?**
We logged every sensor input, so we could run all three controllers on exactly the same recorded movement. The replay reproduced every command the live robot received, sample for sample. It shows what each controller would have asked for, not how the person would have moved differently, which we state as a limitation.

**Why a hidden Markov model and not deep learning?**
We had only 32 labelled training trials. A hidden Markov model trains on little data, its three phases are explainable, and it runs in real time. Because of the slow-only rule, a wrong phase can never make the robot faster.

**How accurate is the phase recognition?**
About 79% on held-out team trials and a median of 69% per participant on people it never saw. A phase error only changes the reduced-speed limit in the outer zone; it never removes a stop.

**Is this a certified safety system?**
No. It is a research prototype using the robot's ordinary speed controls, not a safety-rated stop. A site system would need safety-rated hardware and validation against ISO 10218 and ISO/TS 15066.

**How fast does the robot actually stop?**
A median of 0.16 seconds after the request and never more than 0.23 seconds. Adding the sensing and processing delays gives about 0.31 seconds in 95% of cases, so we recommend allowing 0.5 seconds rather than the 0.4 we assumed.

**What went wrong, and what would you do differently?** (adversity question: answer honestly)
Midway through, the distance reference in the software changed, so the first six participants were measured to a fixed point rather than the moving panel. We analysed the two versions separately and say so in the paper. Next time we would freeze the software version before the first participant and log the reference point beside every distance.

**Why only 12 participants?**
Each session took about 30 minutes of robot time with lab staff present, within one semester. Twelve is small, so we use the person as the unit of analysis and report effects that held for all 12, rather than claiming population-level results.

**Did participants feel safe?**
Yes, they rated all three controllers as safe and could not tell them apart: their "safest" picks were spread 3, 5 and 3, which is chance. Feeling relaxed rose with each block whatever the controller, which is a familiarity effect.

**What about cost and carbon?**
We did not measure either, so we make no claim. The extra costs are tracking equipment, calibration, maintenance and training; any carbon effect would need energy measurements compared with the manual process.

**Who does what in the team?**
Zenan: software and technical integration. Luke: coordination with the lab staff and supervisors. Michael: physical setup and assembly. All three designed the experiment and wrote the paper. Each person should answer questions about their own part.

**How did you use AI?**
AI tools helped with analysis code, figures and editing, and this is declared in the paper.

## Media and setup

The deck is self-contained: photos and native charts, no video or internet needed. Faces are blurred in all photos. If you add a video clip, check consent, blur faces and re-time the run.
