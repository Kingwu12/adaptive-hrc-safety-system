# Paper v3.2 (internal, 3 Oct 2026): what changed from v3.1

v3.1 is what the supervisors are reviewing. It is unchanged on `main` and in `paper/dist/`. v3.2 lives on branch `paper-v3.2` and is not to be sent until the supervisors' feedback on v3 has been applied on top of it.

| Section | v3.1 | v3.2 |
|---|---|---|
| Abstract | 11 study codes; descriptive; H1 partly supported | 12 participants; exact same-input replay; lead, unnecessary stops, distance-error coverage, measured robot stopping |
| Contributions | Descriptive distance and motion analysis; item-by-item questionnaires | Same-input comparison of all 12; ratings linked to controller |
| Participants | "12 people, but codes cannot be linked to people" | Identity checked: one sitting per code; helmet height separates codes that share a reused body profile; the 12th person (two codes) merged and included with 8 trials |
| Robot data processing | Brief/sustained stop classification | Adds the exact replay method, the hindsight unnecessary-stop definition, lead time, distance-error sensitivity, measured stopping time and person-level statistics |
| Questionnaire methods | Grouped by block; no tests | Linked to controller from the trial records; Friedman, Wilcoxon, order and perception-measurement tests |
| Results | Logged totals; 33-trial same-input switching ratio | Logged totals kept briefly; new "Same-Input Comparison" subsection and Table V |
| Reported experience | Block C chosen safest | Mapped to controllers, the choices are at chance; the C preference is an order effect (relaxation rises across blocks, p = 0.011) |
| Model validation | 79.4% on held-out operators | Adds a held-out test on all 12 participants: median 69% per person, as a lower bound |
| Discussion | Switching; H1 partly supported | What prediction buys (margin against distance error), the cost (brief switching, unnoticed), H1 supported on safety and partly on efficiency, and the task as the limit on the gain |
| Safety and efficiency | "End-to-end response not measured" | Measurable reaction chain about 0.31 s at the 95th percentile against T = 0.4 s; recommends T = 0.5 s |
| Limitations, future work, conclusion | Identity, versions, unmeasured response | Updated to the new evidence |
| Removed for space | "Coverage of the Planned Measures"; complete-response sensitivity table | — |

Kept for the conference version, not in v3.2: the trunk-intent predictor fix.

Build: `cd paper && latexmk -pdf main.tex` (10 pages). Numbers come from `scripts/make_publication_tables.py`, which reads `data/analysis/publication/*.json`.
