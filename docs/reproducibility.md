# Reproducing the software and research artifacts

Run commands from the repository root using the Python environment in the [quickstart](../README.md#run-without-hardware). Record `git rev-parse HEAD` and `python -m pip freeze` with results. The quickstart uses the package's dependency ranges; [requirements-lab-py312.txt](../requirements-lab-py312.txt) records a separate Windows lab environment, including the optional robot dependency.

## Choose the evidence you want to reproduce

| Task | Public checkout sufficient? | Entry point |
|---|---|---|
| Worked sensor transform | Yes; invented poses, no hardware | `scripts/demo_sensor_fusion.py` |
| Parser/body/controller regressions | Yes; synthetic fixtures and included development artifacts | `python -m pytest` |
| Controller simulation and ablations | Yes; generated trajectories | `scripts/run_simulation.py` |
| Mock live supervision self-test | Yes; fake source and simulated clock | `scripts/live_run.py --selftest` |
| Check eligibility of included pilot recordings | Yes, for the specified P03–P05 development subset | `scripts/train_pilot_hmm.py --check-only` |
| Compile the empirical manuscript | Yes, plus a TeX engine; uses committed assets | `scripts/build_paper.py --compile-only` |
| Recompute final telemetry/questionnaire findings | No; controlled-access study inputs required | Full paper build |
| Validate physical tracking/robot performance | No; apparatus and independent measurements required | Lab protocol and installation qualification |

## 1. Sensor integration tutorial

```text
python scripts/demo_sensor_fusion.py --out work/synthetic-fusion-demo.json
python -m pytest tests/test_sensor_fusion_demo.py tests/test_body_tracking.py
```

The JSON is labelled synthetic and the script uses its own illustrative transform. It neither changes the stored lab calibration nor produces participant records. See [the tutorial](helmet-xsens-integration.md) for expected values.

## 2. Controller simulation and replay

```text
python scripts/run_simulation.py
python scripts/live_run.py --selftest
python scripts/replay.py --controller all
```

The simulation fits its example HMM from separately seeded synthetic training traces, runs the controllers and ablations, and writes `data/logs/*.jsonl` plus `data/analysis/metrics.json`. These paths already contain committed example outputs, so a rerun can produce tracked changes.

**Replay format matters:** `replay.py` generates a seeded synthetic trace by default or reads its `--trace` NumPy `.npz` format. It does not directly ingest dashboard schema-v3 JSONL or arbitrary recorded mocap JSONL. The older live runner's description of direct replay is historical; use an explicit, validated conversion if extending replay to another schema.

Synthetic results test controller behaviour under the generator's assumptions. They do not estimate participant performance. `make simulation-tables` explicitly regenerates legacy simulation tables; those are not the empirical tables included by the canonical manuscript.

## 3. Pilot model development

```text
python scripts/train_pilot_hmm.py --participants P03,P04,P05 --validation participant --check-only
```

This checks the development subset. Inspect the reported eligibility and label coverage before training. The full training command is:

```text
python scripts/train_pilot_hmm.py --participants P03,P04,P05 --validation participant
```

Training writes a candidate artifact rather than promoting it to `data/models/pilot_hmm.json`. A newly fitted candidate is not guaranteed to reproduce the historical active model: fitting code and dependency versions have evolved. Report the model hash, feature order, split and causal/offline metric separately. Do not substitute the candidate's scores for the manuscript's recorded model validation.

The head/body feature contract needs full body observations. Older pilot files may not contain them. An empty eligible body-training set is not a reason to invent features or reuse evaluation data as independent validation.

## 4. Paper compilation and full analysis

Compile the existing empirical paper without study records:

```text
python -m pip install -e ".[paper]"
python scripts/build_paper.py --compile-only --engine /path/to/tectonic
```

With a supported engine on PATH, omit `--engine`. This compiles the committed manuscript, figures and tables. It proves that those assets build; it does not independently recompute their statistics.

A complete analysis rebuild requires the telemetry inventory, the referenced raw source folders, original questionnaire export and model snapshot described in [paper/README.md](../paper/README.md):

```text
python scripts/build_paper.py --source-root /path/to/controlled-study-root --engine /path/to/tectonic
```

The source root resolves raw paths named by the inventory. The questionnaire export and inventory themselves occupy the ignored repository paths documented in the paper guide. The build runs telemetry and questionnaire analyses, generates empirical assets, checks results independently, compiles TeX and checks that the raw source hashes did not change. Missing controlled inputs should fail visibly; do not substitute simulation output.

`make paper` means the full empirical build. It is not the public compile-only shortcut. LaTeX remains the master when reviewing edits through Google Docs or Overleaf.

## 5. What the tests establish

The suite exercises malformed packets, frame transforms, stale inputs, recognition contracts, command bounds, task sequencing and recording failures. Some transport tests use local sockets. Tests use mocked robot responses and cannot verify braking distance, actual output latency, calibration accuracy, physical grip, helmet fit or participant safety.

Current source, a historical recording and a new analysis are different versions of evidence. Keep the recorded collection mode, geometry source, model/config fingerprint and source revision with each result. Consult the paper for the conclusions supported by the final study.
