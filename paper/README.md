# Final paper workspace

`main.tex` is the existing canonical IEEEtran paper. `main.pdf` is its compiled nine-page academic manuscript, containing a comparison with prior methods, system design, model development, experimental methods, telemetry and questionnaire results, discussion and references. Recovery operations and author checks are kept in separate notes.

## Build

From the repository root with Python 3.10 or later:

```text
python -m pip install -e ".[paper]"
python scripts/build_paper.py --source-root .. --engine /path/to/tectonic
```

`latexmk` is also supported. If an engine is on PATH, omit `--engine`. For a fresh public checkout, compile the manuscript using the included generated assets. This mode does not load participant records:

```text
python scripts/build_paper.py --compile-only --engine /path/to/tectonic
```

The full build runs telemetry analysis, questionnaire analysis, figure/table generation, independent numeric checks and TeX compilation. It requires separately supplied controlled-access study inputs; these are intentionally excluded from GitHub. It verifies unchanged source hashes, resolved references, no overfull lines and a maximum ten-page PDF. Missing TeX engines cause a failure rather than a silently skipped PDF. `build-verification.json` records the PDF hash and page count; rendered visual inspection is separate.

`make paper` runs the full empirical build with private inputs available. `make sim` and `make simulation-tables` are separate explicit targets. Simulation tables are not inputs to `main.tex`.

## Inputs and outputs

Paths below are relative to the repository root.

| Location | Purpose |
|---|---|
| `data/recovered-trial-inventory.json` | Telemetry inventory; raw paths are relative to `--source-root` |
| `data/questionnaires/responses-2026-09-19.json` | Original Forms rows, source row numbers and workbook hash |
| `data/models/pilot_hmm.json` | Existing model and stored development validation |
| `data/analysis/recovered/` | Trial metrics, time series and checksums |
| `data/analysis/questionnaires/` | Item responses, complete-set sensitivity and summaries |
| `data/analysis/verification.json` | Independent source-to-summary checks |
| `paper/tables/` and `paper/figures/` | Generated manuscript assets |

The source root currently contains `previous-review/raw-sept09-partial/` and `session-2026-09-10/`. A raw-data rebuild needs these folders. The manuscript can also be compiled directly in Overleaf from `FYP-paper-Overleaf.zip` without rerunning the analyses.

## Verification

- Independent adjacent-row calculations reproduce all 14 trial denominators, gap totals and zero-request fractions.
- Counts and every block-item median/distribution agree with original Forms rows; paired global changes agree independently.
- Every complete-response median/distribution and all 90 paired A-to-C item changes agree with the original Forms rows. Twenty-nine of 30 block medians remain unchanged in the complete-response subset.
- Fresh event-window row counts and all three diagnostic motion-threshold counts are independently checked against the original telemetry.
- The 46 input files checked before/after building are unchanged: 42 complete-set source files, two incomplete-trial metadata files, and the questionnaire/model snapshots.
- The PDF has nine pages, resolved citations and no overflowing text/tables. Scientific figures remain vector graphics.
- Eleven follow-up IDs are not asserted to be eleven unique people. No fabricated values, imputation or inferential controller ranking is included.

Use `../docs/final-review.md` for team review and `../docs/assessor-preparation.md` for technical preparation. This manuscript has not been submitted to or accepted by a journal.
