# Makefile -- reproducible pipeline from logged data to the paper PDF.
#
# The dependency chain is one-directional and each artifact DERIVES from the last:
#   run_simulation.py -> data/analysis/metrics.json
#                     -> make_paper_tables.py -> paper/tables/*.tex
#                     -> latexmk -> paper/main.pdf
# No result number is hand-copied anywhere along the chain.

PYTHON ?= python3
METRICS := data/analysis/metrics.json
TABLES  := paper/tables/three_rung.tex paper/tables/ablation.tex

.PHONY: all sim tables paper test clean

all: paper

# 1. Run the analysis: fit models, run all rungs, emit the metrics JSON + logs.
sim $(METRICS):
	$(PYTHON) scripts/run_simulation.py

# 2. Derive the LaTeX result tables from the metrics JSON.
tables $(TABLES): $(METRICS)
	$(PYTHON) scripts/make_paper_tables.py

# 3. Build the PDF. Regenerates tables first. If latexmk is absent, skip GRACEFULLY
#    with a note rather than failing -- the tables are still produced and committable
#    (e.g. for Overleaf, which compiles the repo itself).
paper: tables
	@if command -v latexmk >/dev/null 2>&1; then \
		cd paper && latexmk -pdf -interaction=nonstopmode main.tex && \
		echo "Built paper/main.pdf"; \
	else \
		echo "NOTE: latexmk not installed -- skipping PDF build."; \
		echo "      Tables in paper/tables/ are up to date; compile main.tex on"; \
		echo "      Overleaf (import this repo) or install latexmk to build locally."; \
	fi

# Convenience: run the test suite (safety invariants live here).
test:
	$(PYTHON) -m pytest -q

# Remove derived artifacts (everything here regenerates from source).
clean:
	rm -f $(METRICS) $(TABLES)
	rm -f data/logs/*.jsonl data/logs/*.npz
	cd paper && rm -f main.pdf main.aux main.log main.out main.fls main.fdb_latexmk main.bbl main.blg main.synctex.gz
