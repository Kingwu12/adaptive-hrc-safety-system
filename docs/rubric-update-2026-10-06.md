# Rubric update, 6 Oct 2026: what changed and what we did

On 6 Oct 2026 Tian Goh (new Chief Examiner for the FYP units) rolled the Final Paper and Final Presentation rubrics back to a simpler previous version. Presentation: **Thursday 29 Oct 2026, 2:00 pm**.

## What the new rubrics change

**Paper.** Same content as before, regrouped from nine criteria into four:

| New category | Weight | Old criteria it replaces |
|---|---:|---|
| Background, context, literature review, research question | 30% | Background 10, Literature 10, Research question 5 |
| Scientific and engineering content | 50% | Method 15, Results 15, Discussion 15, Contribution 5 |
| Structure, figures and tables | 10% | Same (template and 10-page limit are still fail items) |
| Clarity and written expression | 10% | Was 15, including referencing and AI acknowledgement |

New or sharper wording: failures reported "so that another researcher could learn from your results"; novel results "highlighted rather than simply listing measurements"; results "specifically linked back to pre-existing work discussed in the literature review"; "Innovation and Originality" replaces "Contribution to the field".

**Presentation.** Twelve criteria become four: individual contribution 10%, technical elements including constraints and project adaptability 60%, structure and visuals 15%, answers to questions 15%. New emphasis: run "exactly to time", slides without too much text, prepared speaker transitions, and a talk that "could have convinced other students to choose this topic".

## Paper changes (branch `rubric-update-2026-10-06`, on top of v3.2)

| Change | Rubric reason |
|---|---|
| Title now leads with safety and efficiency, drops "exploratory" | King's 2 Sep ruling that the title says safety; v3.2 results are no longer only exploratory |
| Abstract has no abbreviations and is 240 words | IEEE template: self-contained, no abbreviations, 150 to 250 words |
| The three supporting questions now match what v3.2 answers | Introduction must set up the research question |
| New "Gaps addressed by this study" paragraph at the end of Related Work | Critical analysis that identifies gaps; question justified by the review |
| Contributions state the novelty: comparison on identical movement | Innovation and originality |
| Discussion links results back to Byner, Karagiannis, X. Lin (2025, 2026) and Jian | Results linked back to the literature review |
| Limitations end with three lessons for anyone repeating the study | Failures reported so others can learn |
| List-style counts in Results shortened | "Reads like a list of results" is a Pass-level descriptor; also keeps the paper at 10 pages |

Still 10 pages, no overfull lines, all references resolve. **Check before submission:** the gaps paragraph says that in the studies reviewed each controller runs on its own trials. Confirm that against Byner et al. and X. Lin et al. (2026).

## Presentation changes

`presentation/FYP-assessment-presentation-v4.pptx`, built by `presentation/build_v4.py`. Guide, timings and prepared answers: `presentation/FYP-presentation-guide.md`.

- **Results updated to v3.2.** v3 still said the study "does not yet establish a safety or efficiency advantage" from 14 trials. v4 reports the 12-person same-input replay: 970/970 entries covered, a stop requested 0.11 s earlier, 67% against 31% coverage under a 5 cm distance error, the brief-stop cost, and robot stopping time.
- **Built around the rubric, not the paper.** Why care and who benefits, the solution and why we chose it, project management with setbacks, and site constraints (safety, whole-life cost, health, net zero carbon, people, standards).
- **Speakers.** Each person opens with their own contribution. Michael presents the rig and results; Luke presents project management, site constraints and the close.
- **Less text.** 11 slides, native charts and photos, scripts in the speaker notes at about 8:40 of speech (target 9:30 delivered).
- **Prepared answers** rewritten for the new results, including the setback questions the rubric asks to be answered honestly.

Team input, 6 Oct: Michael's setup work (robot position and the PVC pipe structure) is in the slide 5 notes; Luke confirmed the slide 9 timeline.
