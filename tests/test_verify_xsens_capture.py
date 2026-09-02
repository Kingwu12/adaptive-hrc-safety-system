from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from verify_xsens_capture import audit_batch, audit_capture  # noqa: E402


def _record(counter: int, segment_count: int = 23, *, trial: bool = False,
            session: str = "P06-T01", native: str = "P06-T01.mvn") -> dict:
    phase = ("approaching", "working", "retreating")[counter % 3]
    return {
        "schema_version": 3,
        **({
            "session_id": session,
            "mvn_native_recording_confirmed": True,
            "mvn_native_recording_reference": native,
            "model_sha256": "a" * 64,
            "ground_truth_phase": phase,
            "ground_truth_event": "hazard" if counter == 1 else "none",
            "stale": False,
        } if trial else {}),
        "xsens_frame": {
            "sample_counter": counter,
            "time_code_s": counter / 60.0,
            "body_segment_count": segment_count,
            "segments": {
                str(i): {
                    "position_m": [float(i) + counter * 0.01, 0.0, 1.0],
                    "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                }
                for i in range(1, segment_count + 1)
            },
        },
    }


def test_complete_xsens_preflight_passes(tmp_path):
    path = tmp_path / "preflight.jsonl"
    path.write_text(
        "\n".join(json.dumps(_record(i)) for i in range(3)),
        encoding="utf-8")
    failures, summary = audit_capture(path, min_rows=3)
    assert failures == []
    assert summary["unique_sample_counters"] == 3


def test_pelvis_only_capture_fails(tmp_path):
    path = tmp_path / "pelvis-only.jsonl"
    path.write_text(
        "\n".join(json.dumps(_record(i, 1)) for i in range(3)),
        encoding="utf-8")
    failures, _summary = audit_capture(path, min_rows=3)
    assert any("missing body segments" in failure for failure in failures)


def test_complete_trial_batch_passes(tmp_path):
    paths = []
    for trial in range(10):
        path = tmp_path / f"P06-T{trial + 1:02d}.jsonl"
        path.write_text("\n".join(
            json.dumps(_record(
                counter, trial=True, session=f"P06-T{trial + 1:02d}",
                native=f"P06-T{trial + 1:02d}.mvn"))
            for counter in range(6)), encoding="utf-8")
        paths.append(path)
    failures, summaries = audit_batch(paths, min_captures=10, min_rows=6)
    assert failures == []
    assert len(summaries) == 10


def test_trial_batch_rejects_reused_native_recording(tmp_path):
    paths = []
    for trial in range(2):
        path = tmp_path / f"P06-T{trial + 1:02d}.jsonl"
        path.write_text("\n".join(
            json.dumps(_record(
                counter, trial=True, session=f"P06-T{trial + 1:02d}",
                native="reused.mvn"))
            for counter in range(6)), encoding="utf-8")
        paths.append(path)
    failures, _summaries = audit_batch(paths, min_captures=2, min_rows=6)
    assert "native MVN file reference is reused across capture files" in failures
