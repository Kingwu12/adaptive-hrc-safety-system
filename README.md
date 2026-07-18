# adaptive-hrc-safety-system

Reference implementation for the Monash FYP (2026) paper
**"Comparing Static and Adaptive Safety Logic in Human-Robot Ceiling Panel Installation"**
(Wu, Siniakov, Magila).

A UR10e holds a ceiling panel overhead while a human aligns and fastens it. We compare
**three rungs** of safety logic over the **identical** trace:

1. **Fixed-zone** (`FixedZoneController`) — deployed practice: a fixed worst-case
   distance threshold, zone → command, nothing else.
2. **Dynamic SSM** (`DynamicSSMController`) — the *standards* rung: the ISO/TS 15066
   speed-and-separation **envelope** using the **measured** approach speed, and no
   learned model.
3. **Adaptive** (`EnvelopeAdaptiveController`) — the full system: the envelope as a
   certified **floor**, with a *Recognise → Predict → Adapt* layer (Layered HMM state
   recognition + kinematic horizon prediction) **shielded** on top — it may only ADD
   caution, never exceed the envelope.

The sem-2 redesign is documented in full in [`docs/design/sem2-redesign.md`](docs/design/sem2-redesign.md).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                          # must be fully green (safety invariants are locked here)
python scripts/run_simulation.py
```

`run_simulation.py` prints the zone + envelope geometry, the **fitted** transition
matrix, the LHMM recognition report, a **3-rung** metric table, and an **ablation** table
(full system minus prediction; minus the state layer). It writes per-tick decision logs
to `data/logs/{fixed_zone,dynamic_ssm,adaptive}.jsonl` and a machine-readable metrics
JSON to `data/analysis/metrics.json`.

```bash
python scripts/replay.py --controller all   # offline replay/ablation over a logged trace
make paper                                  # regenerate result tables; build the PDF if latexmk present
```

## Pipeline

```
 raw operator position (x,y,z)
        │
        ▼
 FeatureExtractor ──► FeatureFrame(d, d_dot, speed, v_proj, v_lat_frac, a_proj, torso_facing)
        │                 (d = distance to the robot's OCCUPIED COLUMN, not the TCP point)
        ▼
 Layered HMM (upper: approaching/working/retreating/hazard  ·  lower: stationary/walking)
        │  step(x) → posterior p_t
        ▼
 Horizon prediction   time_to_breach(d, v_proj, a_proj)  ⊕  p_hazard   → risk
        │              (constant-accel; one-step p@A kept as superseded component)
        ▼
 DynamicSSMEnvelope   S(t)=max(0,v_proj)·T+C+Sa  →  max permissible speed  (CERTIFIED FLOOR)
        │
        ▼
 ZoneModel (fixed red = S0, yellow = margin·S0, exit hysteresis; RED hard stop on top)
        │
        ▼
 Controller ── FixedZoneController        (zone → command; deployed practice)
            ├─ DynamicSSMController        (envelope alone; the standards rung)
            └─ EnvelopeAdaptiveController  (min(envelope, model); SAFETY INVARIANT first)
        │
        ▼
 DecisionRecord ──► JsonlLogger ─┬─► MockRobot   (records commands)
                                 └─► URRobot      (ur-rtde: speed slider + Dashboard pause/play)
```

## Layout

| Path | What it owns |
|------|--------------|
| `configs/default.yaml` | Every tunable (zones, envelope, horizon, features, LHMM, controller, scenario, robot) |
| `src/hrc_safety/features.py` | Feature extraction; distance to the occupied column |
| `src/hrc_safety/zones.py` | Fixed ISO/TS 15066 zone model + exit hysteresis (the RED hard floor) |
| `src/hrc_safety/envelope.py` | **Dynamic SSM envelope** — speed-aware certified speed floor |
| `src/hrc_safety/horizon.py` | **Horizon prediction** — time-to-breach + risk fusion |
| `src/hrc_safety/lhmm/` | Hand-rolled Layered HMM (upper + lower); fit/step/viterbi |
| `src/hrc_safety/prediction.py` | One-step prediction (Eq.1) — **superseded** anticipation; kept for the ablation |
| `src/hrc_safety/controllers/` | The three rungs (fixed-zone / dynamic-SSM / envelope-adaptive) |
| `src/hrc_safety/metrics.py` | Head-to-head metrics (interruption burden, sensitivity/specificity, lead time) |
| `src/hrc_safety/analysis.py` | One harness that builds a named controller + scores it (shared SSOT) |
| `src/hrc_safety/logging_schema.py` | Shared `DecisionRecord` + JSONL logger |
| `src/hrc_safety/sim/` | Synthetic scenario generator (with distractors) + trace runner |
| `src/hrc_safety/robot/` | `MockRobot` + `URRobot` (ur-rtde) |
| `scripts/run_simulation.py` | End-to-end fit → run 3 rungs + ablation → compare → emit metrics JSON |
| `scripts/replay.py` | Offline replay: run any controller over a logged trace (free ablation) |
| `scripts/make_paper_tables.py` | Derive `paper/tables/*.tex` from the metrics JSON (zero hand transcription) |
| `paper/` | IEEEtran paper skeleton (`main.tex`, `refs.bib`, auto-generated `tables/`) |
| `Makefile` | `make paper` — regenerate tables and build the PDF (latexmk) |
| `sim/ursim/` | URSim docker-compose for command-path validation |
| `tests/test_core.py` | Unit + smoke tests (locks the safety invariants) |
| `docs/design/sem2-redesign.md` | The sem-2 design record — each change with a plain-English WHY |
| `docs/experiment_plan.md` | Physical footprint, pilot calibration, ethics, findings |

## FOUR NON-NEGOTIABLES

1. **RED zone ⇒ protective stop in BOTH conditions, ALWAYS.** The safety invariant is
   checked first in the adaptive decision function, before any model belief or the
   (speed-aware) envelope, and is locked by
   `test_red_zone_always_stops_adaptive_even_if_model_says_working`. **Never merge
   anything that weakens this test.**
2. **The reported transition matrix `A` and emissions MUST be fitted from labelled pilot
   data** (`fit_transitions` / `fit_emissions`). The hand-set values in the config are
   cold-start priors only — reporting them would be circular validation.
3. **Synthetic data never appears in reported results.** The `sim/` scenario exists only to
   exercise the pipeline pilot data will flow through.
4. **The adaptive command NEVER exceeds the safety envelope.** The learned layers are
   shielded: `final speed = min(envelope, model)`, so a recognition or prediction error
   can only add caution, never raise speed. Locked by
   `test_adaptive_never_exceeds_envelope`. **Never merge anything that lets the model
   command above the envelope floor.**

## Optional: real robot / URSim

```bash
pip install -e ".[robot]"                       # ur-rtde
docker compose -f sim/ursim/docker-compose.yml up
python scripts/demo_ursim.py --log adaptive        # replay a logged rung onto URSim live (see also --log fixed_zone)
```

`URRobot` maps full/reduced speed to the RTDE speed slider and a protective stop to the
Dashboard pause (resume = play) — identical in URSim and on hardware. **Lab-review note:** a
real safeguard stop must be wired through the robot's safety I/O, not the Dashboard.

## Paper (LaTeX) — numbers flow from data to the PDF

The paper lives in `paper/` (IEEEtran two-column). Result tables are **auto-generated**:

```
run_simulation.py → data/analysis/metrics.json → make_paper_tables.py → paper/tables/*.tex → main.tex → PDF
```

No result number is ever typed into the paper by hand — the metrics JSON is the single
source, the `.tex` tables derive from it, and `main.tex` `\input`s them. `make paper`
runs the whole chain (and builds the PDF if `latexmk` is installed; otherwise it prints a
note and leaves the up-to-date tables in place).

**Overleaf:** import this GitHub repo directly into Overleaf (New Project → Import from
GitHub) so Luke/Michael can edit `main.tex` without git. Overleaf compiles the committed
tables; re-run `make paper` and push to refresh them. All committed table numbers are
**synthetic** pipeline-validation placeholders and are replaced by pilot data.
