"""Experiment-console service tests using the same fake packets as the Xsens bridge."""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.dashboard_server import DashboardState, safe_id


def test_safe_id_removes_path_characters():
    assert safe_id("../P 01/", "fallback") == "P-01"


def test_dashboard_state_records_enriched_labelled_frames(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    base = time.monotonic()
    for i in range(12):
        wall = base + i / 60.0
        state.on_sample(i / 60.0, (1.5 - i * 0.01, 0.2, 1.0), True, wall)
        state.tick()

    snap = state.snapshot()
    assert snap["connected"] is True
    assert snap["hmm_state"] in {"approaching", "working", "retreating", "hazard"}
    assert snap["feature"]["speed"] > 0

    state.mark_calibrated()
    state.start_session("P/01", "T 01")
    state.set_label("approaching")
    state.tick()
    result = state.stop_session()

    path = tmp_path / result["path"].split("/")[-1]
    row = json.loads(path.read_text().splitlines()[0])
    assert row["participant_id"] == "P-01"
    assert row["trial_id"] == "T-01"
    assert row["ground_truth"] == "approaching"
    assert row["features"]["v_proj"] > 0
    assert set(row["hmm_posterior"]) == {"approaching", "working", "retreating", "hazard"}
