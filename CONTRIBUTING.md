# Contributing and reusing the project

Start with the [README](README.md), [integration tutorial](docs/helmet-xsens-integration.md) and [architecture](docs/architecture.md). Use Python 3.12 in a local virtual environment and install `.[dev]`. The [reproducibility guide](docs/reproducibility.md) distinguishes public examples from controlled study inputs.

## Make a reviewable change

Describe the problem, the resulting behaviour, the relevant source/data format and the checks you ran. Keep installation-specific values in configuration. Preserve documented units, frame directions, quaternion order and clock semantics when changing sensor code. A schema or model feature-order change needs an explicit migration/version explanation.

For a tracking change, cover at least the affected transform or parser and its failure cases. The existing tests demonstrate head-turn invariance, common-translation cancellation, stale/skewed input rejection and hand-based control geometry. Run:

```text
python scripts/demo_sensor_fusion.py
python -m pytest tests/test_sensor_fusion_demo.py tests/test_body_tracking.py tests/test_mocap_bridge.py tests/test_natnet_transport.py
```

Run the full `python -m pytest` suite before submitting changes to live orchestration or controllers. Some tests open local loopback sockets; they do not establish actual sensor/network performance. Dashboard changes also need the checks in [dashboard/package.json](dashboard/package.json) and the existing Windows workflow.

## Preserve the research contract

- Keep synthetic demonstrations explicitly labelled and separate from empirical results.
- Retain raw sources unchanged. Exclusions, gaps and analysis transformations must be traceable.
- Do not infer controller identity from questionnaire block letters or equate restarted session IDs with unique people.
- Keep recognition inputs consistent with the fitted model's recorded feature order. Evaluate a new model before promotion.
- Preserve the fixed-red and command-bound tests within their documented operating modes. A passing software invariant is not a certification claim.
- Reconcile accepted manuscript edits into `paper/main.tex`; do not create a competing master paper.
- Keep participant Forms exports, videos, identity mappings, native recordings and new trial captures out of public commits. `.gitignore` is only a guardrail; review the actual staged file list.

Do not run the one-off robot-motion scripts to test documentation. A different cell needs its own measured transforms, mounting offsets and physical validation.

## Attribution and reproducible references

When referring to this implementation, cite the repository URL and exact commit, together with the manuscript title and authors in the README. The project has no journal DOI asserted here. Distinguish your modifications and experiments from the original study.

Package metadata currently declares MIT, but the checkout has no standalone LICENSE file. The authors should reconcile that metadata with a confirmed license text before others rely on it for redistribution. Vendor SDK components retain their own terms; this guide does not grant rights to those components or to study recordings.

## Report an issue

Include the commit, OS/Python version, command, expected and observed behaviour, and a minimal synthetic reproducer where possible. Remove credentials, names and participant records from logs before attaching them. For hardware-specific behaviour, state which sensor/firmware/stream configuration was actually used and distinguish observed behaviour from a simulated test.
