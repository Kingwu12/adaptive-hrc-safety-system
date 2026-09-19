# Canonical empirical manuscript. Simulation is a separate explicit target.
PYTHON ?= python3
SOURCE_ROOT ?= ..
TEX_ENGINE ?=

.PHONY: all paper tables sim simulation-tables test readiness qualification clean
all: paper

paper:
	$(PYTHON) scripts/build_paper.py --source-root "$(SOURCE_ROOT)" $(if $(TEX_ENGINE),--engine "$(TEX_ENGINE)",)

tables:
	$(PYTHON) scripts/analyse_recovered.py --source-root "$(SOURCE_ROOT)"
	$(PYTHON) scripts/analyse_questionnaires.py
	$(PYTHON) scripts/make_empirical_paper_assets.py
	$(PYTHON) scripts/verify_empirical_analysis.py --source-root "$(SOURCE_ROOT)"

sim:
	$(PYTHON) scripts/run_simulation.py

simulation-tables: sim
	$(PYTHON) scripts/make_paper_tables.py

test:
	$(PYTHON) -m pytest -q

readiness:
	$(PYTHON) scripts/research_readiness.py

qualification:
	$(PYTHON) scripts/verify_xsens_capture.py --trial-batch --qualification-dir data/xsens --report data/verification/qualification-batch.json

# Only TeX intermediates are removed; never raw evidence or analysis inputs.
clean:
	$(PYTHON) -c "from pathlib import Path; [p.unlink() for p in Path('paper').glob('main.*') if p.suffix in ('.aux','.log','.out','.fls','.bbl','.blg','.fdb_latexmk')]"
