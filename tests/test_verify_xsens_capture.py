from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from verify_xsens_capture import audit_batch, audit_capture  # noqa: E402


def _record(counter: int, segment_count: int = 23, *, trial: bool = False,
            session: str = "Q01-T01", native: str = "Q01-T01.mvn",
            planned_event: str = "rapid intrusion",
            controller: str = "fixed zone") -> dict:
    phase = ("approaching", "working", "retreating")[counter % 3]
    event = "none"
    if counter == 1 and planned_event == "rapid intrusion":
        event = "hazard"
    elif counter == 1 and planned_event == "distractor":
        event = "distractor"
    return {
        "schema_version": 3,
        **({
            "session_id": session,
            "mvn_native_recording_confirmed": True,
            "mvn_native_recording_reference": native,
            "motive_recording_reference": native.replace(".mvn", ".tak"),
            "video_recording_reference": native.replace(".mvn", ".mp4"),
            "model_sha256": "a" * 64,
            "ground_truth_phase": phase,
            "ground_truth_event": event,
            "collection_mode": "qualification",
            "block_label": "ABC"[(int(session.split("T")[-1]) - 1) // 3]
            if "-T" in session and int(session.split("T")[-1]) <= 9 else "A",
            "within_block_trial": ((int(session.split("T")[-1]) - 1) % 3) + 1
            if "-T" in session else 1,
            "controller_condition": controller,
            "planned_event": planned_event,
            "controller_decision": {
                "command": "full_speed", "speed_fraction": 1.0,
                "output_applied": True,
            },
            "controller_output_applied": True,
            "recorded_monotonic_s": 1000.0 + counter / 60.0,
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
    events = ("clean", "distractor", "rapid intrusion")
    controllers = ("fixed zone", "reactive SSM", "predictive SSM")
    for trial in range(10):
        path = tmp_path / f"Q01-T{trial + 1:02d}.jsonl"
        planned_event = events[trial % 3]
        controller = controllers[(trial // 3) % 3]
        path.write_text("\n".join(
            json.dumps(_record(
                counter, trial=True, session=f"Q01-T{trial + 1:02d}",
                native=f"Q01-T{trial + 1:02d}.mvn",
                planned_event=planned_event, controller=controller))
            for counter in range(6)), encoding="utf-8")
        event_path = path.with_name(path.stem + ".events.jsonl")
        event_path.write_text("\n".join([
            json.dumps({"event": "shared_sync_marker"}),
            json.dumps({
                "event": "trial_aborted" if trial == 9 else "trial_completed",
            }),
        ]) + "\n", encoding="utf-8")
        path.with_name(path.stem + ".manifest.json").write_text(json.dumps({
            "session_id": f"Q01-T{trial + 1:02d}",
            "outcome": "aborted" if trial == 9 else "completed",
            "native_mvn": f"Q01-T{trial + 1:02d}.mvn",
            "native_motive": f"Q01-T{trial + 1:02d}.tak",
            "consented_video": f"Q01-T{trial + 1:02d}.mp4",
        }) + "\n", encoding="utf-8")
        paths.append(path)
    failures, summaries = audit_batch(paths, min_captures=10, min_rows=6)
    assert failures == []
    assert len(summaries) == 10


def test_trial_batch_rejects_reused_native_recording(tmp_path):
    paths = []
    for trial in range(2):
        path = tmp_path / f"Q01-T{trial + 1:02d}.jsonl"
        path.write_text("\n".join(
            json.dumps(_record(
                counter, trial=True, session=f"Q01-T{trial + 1:02d}",
                native="reused.mvn"))
            for counter in range(6)), encoding="utf-8")
        path.with_name(path.stem + ".events.jsonl").write_text(
            "\n".join([
                json.dumps({"event": "shared_sync_marker"}),
                json.dumps({
                    "event": "trial_aborted" if trial else "trial_completed",
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        path.with_name(path.stem + ".manifest.json").write_text(json.dumps({
            "session_id": f"Q01-T{trial + 1:02d}",
            "outcome": "aborted" if trial else "completed",
            "native_mvn": "reused.mvn",
            "native_motive": "reused.tak",
            "consented_video": "reused.mp4",
        }) + "\n", encoding="utf-8")
        paths.append(path)
    failures, _summaries = audit_batch(paths, min_captures=2, min_rows=6)
    assert "native MVN file reference is reused across capture files" in failures
