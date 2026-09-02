from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from verify_xsens_capture import audit_capture  # noqa: E402


def _record(counter: int, segment_count: int = 23) -> dict:
    return {
        "schema_version": 2,
        "xsens_frame": {
            "sample_counter": counter,
            "time_code_s": counter / 60.0,
            "body_segment_count": segment_count,
            "segments": {
                str(i): {
                    "position_m": [float(i), 0.0, 1.0],
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

