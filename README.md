# adaptive-hrc-safety-system

Reference implementation for the Monash FYP (2026) paper
**"Comparing Static and Adaptive Safety Logic in Human-Robot Ceiling Panel Installation"**
(Wu, Siniakov, Magila).

A UR10 CB3 holds a lightweight surrogate panel while a human performs the approved task.
This repository is a research prototype, not a certified safety system. We compare
**three rungs** of safety logic over the **identical** trace:

1. **Fixed-zone** (`FixedZoneController`) — deployed practice: a fixed worst-case
   distance threshold, zone → command, nothing else.
2. **Dynamic envelope** (`DynamicSSMController`) — a simplified, standards-informed
   speed-and-separation comparator using the **measured** approach speed, and no
   learned model.
3. **Adaptive** (`EnvelopeAdaptiveController`) — the full system: the envelope as a
   deterministic **command bound**, with a *Recognise → Predict → Adapt* layer (Layered HMM state
   recognition + kinematic horizon prediction) **shielded** on top — it may only ADD
   caution, never exceed the envelope.

The current scope and real-run gates are in
[`docs/research-readiness-audit-2026-09-02.md`](docs/research-readiness-audit-2026-09-02.md).
Older design notes use “certified floor” as architecture shorthand; that wording is not
a certification claim and has been superseded by the readiness audit.

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

# Local Xsens experiment console (run both in separate terminals)
python scripts/dashboard_server.py          # localhost-only sensor service
cd dashboard && npm run dev                 # open http://localhost:3000

# After collecting labelled pilot loops (requires >=3 complete three-phase loops).
# Install the training-only Gaussian-mixture fitter, filter out bring-up files,
# and validate on people absent from model fitting.
python -m pip install -e ".[training]"
python scripts/train_pilot_hmm.py --participants P03,P04,P05 --validation participant --check-only
python scripts/train_pilot_hmm.py --participants P03,P04,P05 --validation participant
# Restart dashboard_server.py; it loads data/models/pilot_hmm.json automatically.

# On a Windows 10/11 machine, run Xsens Analyze/Animate with the Awinda
# dongle attached. Stream Position + Quaternion over UDP to this Mac:9763.
# Before a real run, the console must show Xsens 23/23 segments. Schema v3
# persists every segment XYZ + quaternion and refuses pelvis-only recording.
# The run cannot start until calibration was marked within five minutes and a
# visible, unique native MVN filename/path is entered.

# After the 10 pre-study qualification runs (replace P06 with the pilot ID):
python scripts/verify_xsens_capture.py data/xsens/P06-T*.jsonl \
  --trial-batch --min-captures 10 \
  --report data/verification/prestudy-xsens-batch.json
# Commit the verified implementation, then freeze the exact study release:
python scripts/freeze_study_release.py data/verification/prestudy-xsens-batch.json
python scripts/research_readiness.py --stage collection

# Optional group viewing on trusted lab Wi-Fi (remote browsers are view-only)
python scripts/dashboard_server.py --share
cd dashboard && npm run dev -- --host 0.0.0.0
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
Layered GMM-HMM (observation: d, v_proj, speed, heading alignment)
        │          (upper task phase: approaching/working/retreating · lower: stationary/walking)
        │  step(x) → posterior p_t
        ▼
 Independent event prediction   time_to_breach(d, v_proj, a_proj) → rapid-intrusion risk
        │              (constant-accel; one-step p@A kept as superseded component)
        ▼
 DynamicSSMEnvelope   S(t)=max(0,v_proj)·T+C+Sa  →  prototype command bound
        │
        ▼
 ZoneModel (fixed red = S0, yellow = margin·S0, exit hysteresis; RED hard stop on top)
        │
        ▼
 Controller ── FixedZoneController        (zone → command; deployed practice)
            ├─ DynamicSSMController        (simplified envelope comparator)
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
| `src/hrc_safety/envelope.py` | **Dynamic envelope** — speed-aware prototype command bound |
| `src/hrc_safety/horizon.py` | **Horizon prediction** — time-to-breach + risk fusion |
| `src/hrc_safety/lhmm/` | Hand-rolled Layered HMM (upper + lower); fit/step/viterbi |
| `src/hrc_safety/prediction.py` | One-step prediction (Eq.1) — **superseded** anticipation; kept for the ablation |
| `src/hrc_safety/controllers/` | The three rungs (fixed-zone / dynamic-SSM / envelope-adaptive) |
| `src/hrc_safety/metrics.py` | Head-to-head metrics (interruption burden, sensitivity/specificity, lead time) |
| `src/hrc_safety/analysis.py` | One harness that builds a named controller + scores it (shared SSOT) |
| `src/hrc_safety/logging_schema.py` | Shared `DecisionRecord` + JSONL logger |
| `src/hrc_safety/mocap/xsens_transport.py` | Full MXTP02 packet capture plus pelvis compatibility view |
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

1. **RED zone ⇒ stop request in BOTH conditions, ALWAYS.** The software invariant is
   checked first in the adaptive decision function, before any model belief or the
   (speed-aware) envelope, and is locked by
   `test_red_zone_always_stops_adaptive_even_if_model_says_working`. **Never merge
   anything that weakens this test.**
2. **The reported transition matrix `A` and mixture emissions MUST be fitted from labelled
   pilot data.** The hand-set values in the config are
   cold-start priors only — reporting them would be circular validation.
3. **Synthetic data never appears in reported results.** The `sim/` scenario exists only to
   exercise the pipeline pilot data will flow through.
4. **The adaptive command NEVER exceeds the deterministic envelope.** The learned layers are
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

`URRobot` maps full/reduced speed to the RTDE speed slider and a stop request to Dashboard
pause plus slider zero. That path is **not safety-rated**. It is for URSim and controlled
engineering bring-up only; participant SSM trials require an independently validated
safeguard output through the robot safety chain.

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
