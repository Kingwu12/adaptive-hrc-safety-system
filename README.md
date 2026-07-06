# adaptive-hrc-safety-system

Reference implementation for the Monash FYP (2026) paper
**"Comparing Static and Adaptive Safety Logic in Human-Robot Ceiling Panel Installation"**
(Wu, Siniakov, Magila).

A UR10e holds a ceiling panel overhead while a human aligns and fastens it. We compare
two safety controllers over the **identical** trace:

- **Static baseline** — a fixed distance threshold: zone → command, nothing else.
- **Adaptive** — a *Recognise → Predict → Adapt* pipeline: sensors → features →
  Layered HMM state recognition → one-step prediction → adaptive Speed-and-Separation
  zone control per ISO/TS 15066.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                          # must be fully green (safety invariant is locked here)
python scripts/run_simulation.py
```

`run_simulation.py` prints the zone geometry, the **fitted** transition matrix, the LHMM
recognition report, and a side-by-side metric table; it writes per-tick decision logs to
`data/logs/{static,adaptive}.jsonl`.

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
 Prediction   p_{t+1} = normalize(p_t @ A)          (paper Eq.1)
        │
        ▼
 ZoneModel (red = S0, yellow = margin·S0, exit hysteresis)
        │
        ▼
 Controller ── StaticController      (zone → command)
            └─ AdaptiveController    (Table I; SAFETY INVARIANT checked first)
        │
        ▼
 DecisionRecord ──► JsonlLogger ─┬─► MockRobot   (records commands)
                                 └─► URRobot      (ur-rtde: speed slider + Dashboard pause/play)
```

## Layout

| Path | What it owns |
|------|--------------|
| `configs/default.yaml` | Every tunable (zones, features, LHMM, controller, scenario, robot) |
| `src/hrc_safety/features.py` | Feature extraction; distance to the occupied column |
| `src/hrc_safety/zones.py` | ISO/TS 15066 zone model + exit hysteresis |
| `src/hrc_safety/lhmm/` | Hand-rolled Layered HMM (upper + lower); fit/step/viterbi |
| `src/hrc_safety/prediction.py` | One-step prediction (Eq.1) + hazard probability |
| `src/hrc_safety/controllers/` | Static baseline + adaptive controller |
| `src/hrc_safety/metrics.py` | Head-to-head metrics + recognition report |
| `src/hrc_safety/logging_schema.py` | Shared `DecisionRecord` + JSONL logger |
| `src/hrc_safety/sim/` | Synthetic scenario generator + trace runner |
| `src/hrc_safety/robot/` | `MockRobot` + `URRobot` (ur-rtde) |
| `scripts/run_simulation.py` | End-to-end fit → run both → compare |
| `sim/ursim/` | URSim docker-compose for command-path validation |
| `tests/test_core.py` | Unit + smoke tests (locks the safety invariant) |
| `docs/experiment_plan.md` | Physical footprint, pilot calibration, ethics, findings |

## THREE NON-NEGOTIABLES

1. **RED zone ⇒ protective stop in BOTH conditions, ALWAYS.** The safety invariant is
   checked first in the adaptive decision function, before any model belief, and is locked
   by `test_red_zone_always_stops_adaptive_even_if_model_says_working`. **Never merge
   anything that weakens this test.**
2. **The reported transition matrix `A` and emissions MUST be fitted from labelled pilot
   data** (`fit_transitions` / `fit_emissions`). The hand-set values in the config are
   cold-start priors only — reporting them would be circular validation.
3. **Synthetic data never appears in reported results.** The `sim/` scenario exists only to
   exercise the pipeline pilot data will flow through.

## Optional: real robot / URSim

```bash
pip install -e ".[robot]"                       # ur-rtde
docker compose -f sim/ursim/docker-compose.yml up
```

`URRobot` maps full/reduced speed to the RTDE speed slider and a protective stop to the
Dashboard pause (resume = play) — identical in URSim and on hardware. **Lab-review note:** a
real safeguard stop must be wired through the robot's safety I/O, not the Dashboard.
