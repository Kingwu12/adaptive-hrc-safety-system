# Final presentation: rehearsal and rubric guide

**Thursday 29 October 2026, 2:00 pm.** Use **FYP-assessment-presentation-v4.3.pptx**. It is built by `python3 presentation/build_v43.py` from v4.2, which `build_v42.py` builds from v4 (the 6 Oct deck, uploaded to Drive as v4.1), which is rebuilt by `build_v4.py`. The speaker notes hold the full script for each slide. Rehearse from them until you can say each slide in your own words; reading from the slides is a fail item in the rubric.

v4.3 (23 Oct 2026) changes, from team feedback:

1. **Acknowledgement of Country** as the first line of slide 1 (spoken, not on screen): "We acknowledge the Traditional Owners of the land we are meeting on, and pay our respects to their Elders." Unit staff on Ed #112: a quick one would suffice.
2. **Slide 2 shows the task on a real site** (two people holding a board to a ceiling; photo by Qole Pejorian, CC BY 2.0, credited on the slide), with our lab version below it.
3. **Slide 4 images cropped** to their content.
4. **Carbon removed** from slide 11 and its script. The prepared answer on cost and carbon stays below.

v4.2 (14 Oct 2026) added, from supervisor feedback:

1. **The research question on screen early** (slide 2), and a tag on each result slide saying which part of the question it answers; slide 12 answers it back.
2. **More of the actual work:** the participant video on the rig slide, and a new slide 4 with our operator console and the trained phase model running on a person it never saw.
3. **Three minutes per speaker.**

## Running order

**About three minutes each, 8:55 in total**, leaving a minute of buffer before the hard 10-minute stop. Each speaker's script is about 400 words, roughly 2:50 at 140 words a minute; slide changes and pauses fill the rest. These are allocations, not a timed rehearsal: time a real run and aim to land between 8:45 and 9:30.

| Slide | Speaker | Time | Ends at | Focus |
|---|---|---:|---:|---|
| 1 Title | Zenan | 0:30 | 0:30 | Acknowledgement of Country, who we are, roadmap |
| 2 Why this problem matters | Zenan | 0:50 | 1:20 | The task on site and in our lab, why care, who benefits, **the research question** |
| 3 Our solution | Zenan | 0:50 | 2:10 | Three controllers, slow-only rule |
| 4 What we built | Zenan | 0:50 | 3:00 | Operator console and trained model (Zenan's contribution) |
| 5 How we tested it | Michael | 0:40 | 3:40 | 12 people, rotated blocks, same-input replay |
| 6 The test rig | Michael | 0:40 | 4:20 | Robot position and PVC pipe structure (Michael's contribution), video |
| 7 Result 1: as safe? | Michael | 0:50 | 5:10 | 970/970, earlier stop, margin under distance error |
| 8 Result 2: still efficient? | Michael | 0:50 | 6:00 | Brief extra stops, unnoticed, robot stopping time |
| 9 The task is the limit | Luke | 0:40 | 6:40 | A third of each trial stopped; contact-safe mode next |
| 10 Project management | Luke | 0:50 | 7:30 | Plan, setbacks, responses (Luke's contribution) |
| 11 Using it on site | Luke | 0:45 | 8:15 | Safety, cost, health, people, standards |
| 12 Answer and next steps | Luke | 0:40 | 8:55 | Answer to the question, industry meaning, why pick this topic |

**Prepared handovers** (also at the end of the notes on slides 4 and 8):

- End of slide 4, Zenan: "Michael will now show you how we tested it and what we found."
- End of slide 8, Michael: "Luke will now take us through what this means and how we ran the project."

Pass the clicker with the last sentence, not after it.

## Before Thursday

- Michael's setup work (robot position and the PVC pipe structure) is now in the slide 5 notes, and Luke has confirmed the slide 9 timeline.
- **Everyone:** open the deck on the presentation machine, check fonts and charts, and do two timed full runs.

## Rubric coverage (rolled-back rubric, 6 Oct 2026)

| Category | Weight | Where it is covered |
|---|---:|---|
| Individual contribution (per student) | 10% | Each speaker states their own role (slides 4, 6, 10); roles repeated on slide 12. Speak, don't read; dress for a business setting; no filler words. |
| Technical elements, constraints and contextual factors, adaptability | 60% | Why care, who benefits and the research question (2); solution chosen and justified (3); what we built (4); design and conduct for a general audience (5, 6); honest results, each tagged with the part of the question it answers (7, 8, 9); project management with setbacks (10); safety, whole-life cost, health and social factors (11; the rubric also names net zero carbon, which v4.3 took off the slide, so it is covered only by the prepared answer below); answer to the research question and why another student should pick this topic (12). |
| Structural and visual elements | 15% | Problem, solution, test, results, management, context, answer. Photos, native charts, diagrams; text kept short. Two prepared handovers. Target 8:55, about three minutes each. |
| Responsive elements (answers to questions) | 15% | Prepared answers below. Keep each to two or three sentences, then stop. |

Points the old guide covered that the new rubric now stresses:

- "The presentation should not be a summary of your paper." v4 leads with why it matters, the choices we made and what it would take to use on site, not the paper's section order.
- "Could have convinced other students to choose this topic." Luke's closing line on slide 12 does this.
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
Zenan: software and technical integration. Luke: coordination with the lab staff and supervisors. Michael: physical setup, including the robot position and the PVC pipe structure around it. All three designed the experiment and wrote the paper. Each person should answer questions about their own part.

**How did you use AI?**
AI tools helped with analysis code, figures and editing, and this is declared in the paper.

## Media and setup

The deck is self-contained: photos and native charts, no video or internet needed. Faces are blurred in all photos. If you add a video clip, check consent, blur faces and re-time the run.
