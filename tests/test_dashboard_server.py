"""Experiment-console service tests using the same fake packets as the Xsens bridge."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import types
import urllib.error
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.dashboard_server import (ApiHandler, DashboardState,
                                      GuidedRunController, RigControl,
                                      RunCatalog, safe_id)


def test_create_participant_does_not_wait_for_cold_recording_scan(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    # Legacy recording IDs must remain reserved even before history is indexed.
    (tmp_path / "legacy.jsonl").write_text(
        json.dumps({"participant_id": "P12", "t": 0}) + "\n",
        encoding="utf-8",
    )
    catalog = RunCatalog(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    original = catalog._summarize

    def slow_summary(path, stat):
        entered.set()
        assert release.wait(5)
        return original(path, stat)

    monkeypatch.setattr(catalog, "_summarize", slow_summary)
    with ThreadPoolExecutor(max_workers=2) as pool:
        scanning = pool.submit(catalog.catalog)
        try:
            assert entered.wait(2)
            creation = pool.submit(catalog.save_participant, "", None, "participant_study")
            created = creation.result(timeout=2)["participant"]
            assert created["id"] == "P13"
            assert created["run_count"] == 0
            assert created["next_trial"] == "T01"
        finally:
            release.set()
        assert any(row["id"] == "P13" for row in scanning.result()["participants"])


def _full_xsens_frame() -> dict:
    segments = {
        str(segment_id): {
            "position_m": [float(segment_id), 0.0, 1.0],
            "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
        for segment_id in range(1, 24)
    }
    segments["2"]["quaternion_wxyz"] = [0.5, 0.5, 0.5, 0.5]
    return {
        "message_id": "MXTP02", "sample_counter": 17,
        "datagram_counter": 0, "time_code_s": 1.25,
        "avatar_id": 0, "item_count": 23, "body_segment_count": 23,
        "prop_count": 0, "finger_segment_count": 0, "payload_size": 736,
        "received_monotonic_s": time.monotonic(), "segments": segments,
    }


def test_safe_id_removes_path_characters():
    assert safe_id("../P 01/", "fallback") == "P-01"


def test_form_probe_identifies_login_challenge_as_not_public(monkeypatch):
    def login_required(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://docs.google.com/forms/", 401, "Unauthorized", None, None
        )

    monkeypatch.setattr("scripts.dashboard_server.urllib.request.urlopen", login_required)
    ApiHandler._form_status_cache = None

    result = ApiHandler._form_access_status()

    assert result["all_responder_routes_available"] is True
    assert result["all_accessible_without_login"] is False
    assert all(item["requires_monash_login"] for item in result["forms"].values())
    assert all(item["responder_route_available"] for item in result["forms"].values())


def test_form_completion_reports_unconfigured_without_guessing_submission(monkeypatch, tmp_path):
    monkeypatch.delenv("HRC_FORM_COMPLETION_URL", raising=False)
    monkeypatch.delenv("HRC_FORM_COMPLETION_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    result = ApiHandler._form_completion_status({
        "participant_id": ["P07"],
        "stage": ["intake"],
    })

    assert result["tracking_configured"] is False
    assert result["tracking_available"] is False
    assert result["submitted"] is False


def test_form_completion_bridge_returns_only_boolean_status(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true,"submitted":true}'

    monkeypatch.setenv("HRC_FORM_COMPLETION_URL", "https://example.test/exec")
    monkeypatch.setenv("HRC_FORM_COMPLETION_TOKEN", "test-secret")
    monkeypatch.setattr(
        "scripts.dashboard_server.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    result = ApiHandler._form_completion_status({
        "participant_id": ["P07"],
        "stage": ["block"],
        "block": ["B"],
    })

    assert result["tracking_available"] is True
    assert result["submitted"] is True
    assert "answers" not in result


def _write_catalog_run(path, participant, trial, labels, stale_at=(),
                       collection_mode=None):
    session = f"{participant}-{trial}-20260902-120000-abcdef"
    with path.open("w", encoding="utf-8") as handle:
        sample = 0
        for label in labels:
            for _ in range(300):
                row = {
                    "session_id": session,
                    "participant_id": participant,
                    "trial_id": trial,
                    "t": sample / 60.0,
                    "stale": sample in stale_at,
                    "ground_truth": label,
                }
                if collection_mode is not None:
                    row["collection_mode"] = collection_mode
                handle.write(json.dumps(row) + "\n")
                sample += 1


def test_run_catalog_lists_quality_names_and_next_trial(tmp_path):
    labels = [
        "approaching", "working", "retreating", "approaching",
        "working", "hazard", "retreating",
    ]
    _write_catalog_run(tmp_path / "run.jsonl", "P01", "T06", labels, stale_at=(4,))
    catalog = RunCatalog(tmp_path)

    result = catalog.catalog()
    assert result["participants"][0]["id"] == "P01"
    assert result["participants"][0]["next_trial"] == "T07"
    assert result["runs"][0]["quality"]["grade"] == "good"
    assert result["runs"][0]["quality"]["score"] == 100
    assert result["runs"][0]["collection_mode"] == "model_development"

    saved = catalog.save_participant("Alex Example", "P01")
    assert saved["participant"]["name"] == "Alex Example"
    created = catalog.save_participant("Second Person")
    assert created["participant"]["id"] == "P02"
    assert created["participant"]["next_trial"] == "T01"
    assert (tmp_path / "participants.json").exists()


def test_catalog_separates_new_study_participants_from_legacy_development(tmp_path):
    labels = [
        "approaching", "working", "retreating", "approaching",
        "working", "hazard", "retreating",
    ]
    _write_catalog_run(tmp_path / "legacy.jsonl", "P01", "T01", labels)
    _write_catalog_run(
        tmp_path / "study.jsonl", "P06", "T01", labels,
        collection_mode="participant_study")
    catalog = RunCatalog(tmp_path)
    catalog.save_participant("", "P06", "participant_study")

    result = catalog.catalog()
    runs = {row["participant_id"]: row for row in result["runs"]}
    participants = {row["id"]: row for row in result["participants"]}
    assert runs["P01"]["collection_mode"] == "model_development"
    assert runs["P06"]["collection_mode"] == "participant_study"
    assert participants["P01"]["collection_mode"] == "model_development"
    assert participants["P06"]["collection_mode"] == "participant_study"


def test_run_catalog_marks_incomplete_short_attempt_for_repeat(tmp_path):
    _write_catalog_run(tmp_path / "short.jsonl", "P01", "T01", ["unlabelled"])
    catalog = RunCatalog(tmp_path)

    run = catalog.catalog()["runs"][0]
    assert run["quality"]["grade"] == "repeat"
    assert "missing" in " ".join(run["quality"]["reasons"])
    assert RunCatalog._next_trial([{"trial_id": "T01"}, {"trial_id": "T01"}]) == "T03"


def test_dashboard_state_records_enriched_labelled_frames(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    state.on_xsens_frame(_full_xsens_frame())
    base = time.monotonic()
    for i in range(12):
        wall = base + i / 60.0
        position = (1.5 - i * 0.01, 0.2, 1.0)
        state.on_sample(i / 60.0, position, True, wall)
        # OptiTrack supplies the safety-critical absolute position; Xsens is
        # retained as the articulated-motion/logging source.
        state.optitrack_bridge.on_sample(i / 60.0, position, True, wall)
        state.tick()

    snap = state.snapshot()
    assert snap["connected"] is True
    assert snap["xsens_segment_count"] == 23
    assert snap["hmm_state"] in {"approaching", "working", "retreating"}
    assert snap["feature"]["speed"] > 0

    state.mark_calibrated()
    state.start_session(
        "P/01", "T 01", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P01-T01.mvn")
    state.set_label("approaching")
    for i in range(12, 15):
        wall = base + i / 60.0
        position = (1.5 - i * 0.01, 0.2, 1.0)
        state.on_sample(i / 60.0, position, True, wall)
        state.optitrack_bridge.on_sample(i / 60.0, position, True, wall)
        state.tick()
    result = state.stop_session()

    path = tmp_path / result["path"].split("/")[-1]
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    row = next(item for item in rows if item["features"] is not None)
    assert row["participant_id"] == "P-01"
    assert row["schema_version"] == 3
    assert len(row["xsens_frame"]["segments"]) == 23
    assert row["xsens_frame"]["segments"]["2"]["quaternion_wxyz"] == [
        0.5, 0.5, 0.5, 0.5]
    assert row["trial_id"] == "T-01"
    assert row["ground_truth"] == "approaching"
    assert row["ground_truth_phase"] == "approaching"
    assert row["ground_truth_event"] == "none"
    assert row["mvn_native_recording_reference"] == r"C:\MVN\P01-T01.mvn"
    assert row["model_sha256"] == "synthetic-baseline"
    assert row["features"]["v_proj"] > 0
    assert set(row["hmm_posterior"]) == {"approaching", "working", "retreating"}


def test_start_session_rejects_code_changed_since_service_start(tmp_path, monkeypatch):
    import scripts.dashboard_server as service
    state = DashboardState(tmp_path, segment_id=1)
    changed = dict(state.runtime_release)
    changed['files'] = dict(changed['files'])
    changed['files']['scripts/dashboard_server.py'] = 'changed-after-startup'
    monkeypatch.setattr(service, 'release_fingerprint', lambda *args: changed)
    with pytest.raises(ValueError, match='restart it before a new trial'):
        state.start_session('P01', 'T01')
    assert not state.recording


def test_start_session_resets_temporal_model_state(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    state.on_xsens_frame(_full_xsens_frame())
    base = time.monotonic()
    for i in range(8):
        wall = base + i / 60.0
        position = (1.5 - i * 0.01, 0.2, 1.0)
        state.on_sample(i / 60.0, position, True, wall)
        state.optitrack_bridge.on_sample(i / 60.0, position, True, wall)
        state.tick()

    assert state.feature is not None
    assert state.posterior
    state.mark_calibrated()
    state.start_session(
        "P01", "T01", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P01-T01.mvn")

    assert state.feature is None
    assert state.posterior == {}
    assert state.hmm_state is None
    np.testing.assert_allclose(state.hmm.belief, [1 / 3, 1 / 3, 1 / 3])
    state.stop_session()


def test_dashboard_rejects_recording_without_optitrack(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    with pytest.raises(ValueError, match="OptiTrack"):
        state.start_session("P01", "T07")


def test_dashboard_rejects_incomplete_xsens_body_stream(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    frame = _full_xsens_frame()
    frame["segments"] = {"1": frame["segments"]["1"]}
    frame["item_count"] = frame["body_segment_count"] = 1
    state.on_xsens_frame(frame)
    state.tick()
    with pytest.raises(ValueError, match="received 1/23"):
        state.start_session("P01", "T08")


def test_dashboard_rejects_unmarked_calibration_and_missing_native_reference(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_xsens_frame(_full_xsens_frame())
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.tick()
    with pytest.raises(ValueError, match="calibration"):
        state.start_session(
            "P01", "T09", mvn_recording_confirmed=True,
            mvn_recording_reference=r"C:\MVN\P01-T09.mvn")
    state.mark_calibrated()
    with pytest.raises(ValueError, match="filename"):
        state.start_session("P01", "T09", mvn_recording_confirmed=True)


def test_dashboard_rejects_reused_native_recording_reference(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    now = time.monotonic()
    state.on_xsens_frame(_full_xsens_frame())
    state.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (1.0, 0.0, 1.0), True, now)
    state.tick()
    state.mark_calibrated()
    reference = r"C:\MVN\P01-T10.mvn"
    state.start_session(
        "P01", "T10", mvn_recording_confirmed=True,
        mvn_recording_reference=reference)
    later = now + 1 / 60.0
    state.on_sample(1 / 60.0, (0.99, 0.0, 1.0), True, later)
    state.optitrack_bridge.on_sample(
        1 / 60.0, (0.99, 0.0, 1.0), True, later)
    state.tick()
    state.stop_session()
    with pytest.raises(ValueError, match="already used"):
        state.start_session(
            "P01", "T11", mvn_recording_confirmed=True,
            mvn_recording_reference=reference.lower())


def test_guided_protocol_persists_and_applies_labels(tmp_path):
    state = DashboardState(
        tmp_path, segment_id=1, model_path=Path("data/models/pilot_hmm.json"),
        enable_research_output=True,
    )
    state.on_xsens_frame(_full_xsens_frame())
    now = time.monotonic()
    state.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.tick()
    state.mark_calibrated()
    with pytest.raises(ValueError, match="Assigned study slot is A1"):
        state.start_session(
            "P07", "T-wrong", mvn_recording_confirmed=True,
            mvn_recording_reference=r"C:\MVN\P07-T-wrong.mvn",
            block_label="A", within_block_trial=1,
            controller_condition="reactive SSM", planned_event="clean",
            collection_mode="participant_study")
    state.start_session(
        "P01", "T-guided", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P01-T-guided.mvn")

    first = state.snapshot()
    assert first["guided_step"] == 0
    assert first["label"] == "unlabelled"

    state.mark_sync_event()
    state.advance_guided_protocol()
    second = state.snapshot()
    assert second["guided_step"] == 1
    assert second["label"] == "approaching"

    # The server state, rather than browser-local state, remains authoritative.
    state.advance_guided_protocol()
    third = state.snapshot()
    assert third["guided_step"] == 2
    assert third["label"] == "working"
    state.stop_session()
    stopped = state.snapshot()
    assert stopped["guided_step"] is None
    assert stopped["label"] == "unlabelled"


@pytest.mark.parametrize('block,within,controller,identity', [
    ('A',1,'fixed zone','static'),
    ('B',1,'reactive SSM','dynamic_ssm'),
    ('C',2,'predictive SSM','adaptive'),
])
@pytest.mark.parametrize('execution_mode',['operator_confirmed','automatic'])
def test_study_metadata_and_clean_event_are_logged_without_fake_hazard(tmp_path,block,within,controller,identity,execution_mode):
    state = DashboardState(
        tmp_path, segment_id=1, model_path=Path("data/models/pilot_hmm.json"),
        enable_research_output=True,
    )
    state.on_xsens_frame(_full_xsens_frame())
    now = time.monotonic()
    state.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.tick()
    state.mark_calibrated()
    state.start_session(
        "P07", "T01", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P07-T01.mvn",
        block_label=block, within_block_trial=within,
        controller_condition=controller, planned_event="clean",
        collection_mode="participant_study",
        execution_mode=execution_mode,
        motive_recording_reference="P07-T01.tak",
        video_recording_reference="P07-T01.mp4")
    marker = state.mark_sync_event()
    assert marker["sync_marker_count"] == 1

    for _ in range(7):
        state.advance_guided_protocol()
    assert state.snapshot()["guided_step"] == 7
    assert state.snapshot()["event_label"] == "none"

    for index in range(1, 4):
        later = now + index / 60.0
        position = (2.0 - index * 0.01, 0.0, 1.0)
        state.on_sample(index / 60.0, position, True, later)
        state.optitrack_bridge.on_sample(index / 60.0, position, True, later)
        state.tick()
    result = state.stop_session()
    assert Path(result["manifest_path"]).is_file()
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["native_motive"] == "P07-T01.tak"
    assert manifest["consented_video"] == "P07-T01.mp4"
    assert manifest['collection_mode'] == 'participant_study'
    assert manifest['execution_mode'] == execution_mode

    rows = [json.loads(line) for line in Path(result["path"]).read_text().splitlines()]
    row = next(item for item in rows
               if (item.get("controller_decision") or {}).get("condition"))
    assert row["block_label"] == block
    assert row["within_block_trial"] == within
    assert row["controller_condition"] == controller
    assert row["planned_event"] == "clean"
    assert row["collection_mode"] == "participant_study"
    assert row['execution_mode'] == execution_mode
    if execution_mode == 'automatic':
        assert all(item['ground_truth_phase'] == 'unlabelled' for item in rows)
    assert row["ground_truth_event"] == "none"
    assert row["controller_decision"]["condition"] == identity
    assert row["controller_decision"]["command"] in {
        "full_speed", "reduced_speed", "protective_stop",
    }
    assert row["controller_decision"]["output_applied"] is False
    assert row["controller_output_applied"] is False
    events = list(tmp_path.glob("*.events.jsonl"))
    assert len(events) == 1
    event_rows = [json.loads(line) for line in events[0].read_text().splitlines()]
    assert event_rows[0]["event"] == "trial_started"
    assert any(item["event"] == "shared_sync_marker" for item in event_rows)
    assert event_rows[-1]["event"] == "trial_aborted"

    catalog = RunCatalog(tmp_path).catalog()
    assert len(catalog["runs"]) == 1
    assert catalog["runs"][0]["planned_event"] == "clean"
    assert catalog["runs"][0]["collection_mode"] == "participant_study"


def test_qualification_uses_separate_ids_and_structured_schedule(tmp_path):
    catalog = RunCatalog(tmp_path)
    first = catalog.save_participant("", collection_mode="qualification")
    second = catalog.save_participant("", collection_mode="qualification")
    assert first["participant"]["id"] == "Q01"
    assert second["participant"]["id"] == "Q02"
    assert first["participant"]["collection_mode"] == "qualification"

    state = DashboardState(
        tmp_path, segment_id=1, model_path=Path("data/models/pilot_hmm.json"),
        enable_research_output=True,
    )
    state.on_xsens_frame(_full_xsens_frame())
    now = time.monotonic()
    state.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.optitrack_bridge.on_sample(0.0, (2.0, 0.0, 1.0), True, now)
    state.tick()
    state.mark_calibrated()
    state.start_session(
        "Q01", "T01", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\Q01-T01.mvn",
        block_label="A", within_block_trial=1,
        controller_condition="fixed zone", planned_event="clean",
        collection_mode="qualification",
        motive_recording_reference="Q01-T01.tak",
        video_recording_reference="Q01-T01.mp4",
    )
    assert state.snapshot()["collection_mode"] == "qualification"
    assert state.active_controller is not None
    state.stop_session()


def test_guided_protocol_requires_active_recording(tmp_path):
    state = DashboardState(tmp_path, segment_id=1)
    with pytest.raises(ValueError, match="Start guided recording"):
        state.advance_guided_protocol()


def test_rig_status_poll_returns_cached_value_while_probe_is_slow():
    rig = RigControl.__new__(RigControl)
    rig._status_lock = threading.Lock()
    rig._status_refreshing = False
    rig._status_updated = 0.0
    rig._status_cache = {
        "gripper": {"error": "checking rig"},
        "robot": {"reachable": False, "error": "checking rig"},
        "pose": {"available": False, "error": "checking rig"},
    }
    rig.fastening_complete = threading.Event()
    rig.cycle_active = False

    def slow_robot_status():
        time.sleep(0.2)
        return {"reachable": False, "error": "offline"}

    rig.gripper_stats = lambda: {"error": "offline"}
    rig.robot_status = slow_robot_status
    rig.pose_status = lambda: {"available": False, "error": "offline"}

    started = time.monotonic()
    first = rig.status_snapshot({"connected": False})
    assert time.monotonic() - started < 0.1
    assert first["robot"]["error"] == "checking rig"

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with rig._status_lock:
            if not rig._status_refreshing:
                break
        time.sleep(0.01)
    second = rig.status_snapshot({"connected": False}, max_age_s=60.0)
    assert second["robot"]["error"] == "offline"


def test_robot_status_rejects_an_open_port_with_empty_dashboard_replies():
    rig = RigControl.__new__(RigControl)
    rig._dash = lambda *commands: [""] * len(commands)

    status = rig.robot_status()

    assert status["reachable"] is False
    assert "incomplete status" in status["error"]


def test_goto_pose_uses_rtde_and_disconnects(monkeypatch):
    calls = []

    class FakeControl:
        def __init__(self, host):
            calls.append(("connect", host))

        def moveJ(self, q, speed, acceleration):
            calls.append(("moveJ", q, speed, acceleration))
            return True

        def stopJ(self, deceleration):
            calls.append(("stopJ", deceleration))

        def stopScript(self):
            calls.append(("stopScript",))

        def disconnect(self):
            calls.append(("disconnect",))

    monkeypatch.setitem(sys.modules, "rtde_control", types.SimpleNamespace(
        RTDEControlInterface=FakeControl))
    rig = RigControl.__new__(RigControl)
    rig.robot_host = "192.0.2.10"
    rig._poses = {"pose2_top": {"q": [1, 2, 3, 4, 5, 6]}}
    rig.close_program_socket = lambda: calls.append(("close_socket",))
    rig.robot_status = lambda: {
        "reachable": True,
        "robotmode": "Robotmode: RUNNING",
        "safety": "Safetystatus: NORMAL",
    }
    rig.gripper_stats = lambda max_age_s=0.0: {
        "vacuum_A_permille": 600,
        "vacuum_B_permille": 650,
    }

    result = rig.goto_pose("pose2_top")

    assert result["completed"] is True
    assert ("moveJ", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 0.1, 0.15) in calls
    assert calls[-3:] == [("stopJ", 0.5), ("stopScript",), ("disconnect",)]


def test_goto_pose_rejects_low_vacuum_before_connecting(monkeypatch):
    connected = False

    class FakeControl:
        def __init__(self, host):
            nonlocal connected
            connected = True

    monkeypatch.setitem(sys.modules, "rtde_control", types.SimpleNamespace(
        RTDEControlInterface=FakeControl))
    rig = RigControl.__new__(RigControl)
    rig.robot_host = "192.0.2.10"
    rig._poses = {"pose2_top": {"q": [1, 2, 3, 4, 5, 6]}}
    rig.close_program_socket = lambda: None
    rig.robot_status = lambda: {
        "reachable": True,
        "robotmode": "Robotmode: RUNNING",
        "safety": "Safetystatus: NORMAL",
    }
    rig.gripper_stats = lambda max_age_s=0.0: {
        "vacuum_A_permille": 490,
        "vacuum_B_permille": 650,
    }

    with pytest.raises(ValueError, match="vacuum below motion threshold"):
        rig.goto_pose("pose2_top")
    assert connected is False


def test_research_speed_output_is_clamped_and_deduplicated():
    calls = []

    class FakeIO:
        def setSpeedSlider(self, value):
            calls.append(value)
            return True

    rig = RigControl.__new__(RigControl)
    rig._output_lock = threading.Lock()
    rig._io = FakeIO()
    rig._last_speed_fraction = None
    rig._last_output_attempt_at = 0.0
    rig._last_output_failure = None

    first = rig.apply_research_speed_fraction(1.5)
    second = rig.apply_research_speed_fraction(1.0)
    stopped = rig.apply_research_speed_fraction(-0.2)

    assert calls == [1.0, 0.0]
    assert first["applied"] is True and first["changed"] is True
    assert second["status"] == "already_applied"
    assert stopped["speed_fraction"] == 0.0


class FakeGuidedState:
    def __init__(self, step=0, distance=2.0):
        self.config = {"zones": {
            "K": 1.6, "T": 0.4, "C": 0.2, "Sa": 0.1,
            "yellow_margin": 1.6, "hysteresis": 0.05,
        }}
        self.recording = step is not None
        self.step = step
        self.distance = distance
        self.stopped = False
        self.label = "unlabelled" if step in (None, 0, 4, 9) else "retreating"
        self.controller_updated_at = 100.0

    def snapshot(self):
        return {
            "recording": self.recording,
            "guided_step": self.step,
            "connected": True,
            "stale": False,
            "optitrack_connected": True,
            "xsens_segment_count": 23,
            "feature": {"d": self.distance},
            "controller_output_enabled": True,
            "controller_decision": {
                "command": "protective_stop" if self.distance < 1.5 else "full_speed",
                "speed_fraction": 0.0 if self.distance < 1.5 else 1.0,
                "output_applied": True,
            },
            "sync_marker_count": 1,
        }

    def start_session(self, participant, trial,
                      mvn_recording_confirmed=False,
                      mvn_recording_reference=None):
        if not mvn_recording_confirmed:
            raise ValueError("Confirm that native recording is active")
        if not mvn_recording_reference:
            raise ValueError("Enter the visible Windows MVN recording filename")
        self.recording = True
        self.step = 0
        return {"message": "recording", "path": "fake.jsonl"}

    def advance_guided_protocol(self):
        self.step += 1
        return {"message": "advanced", "guided_step": self.step}

    def set_label(self, label):
        self.label = label
        return {"message": f"Ground truth: {label}"}

    def begin_planned_event_window(self, source="robot_lift"):
        self.actions = getattr(self, "actions", [])
        self.actions.append(("event_start", source))
        return {"event_label": "hazard", "source": source}

    def end_planned_event_window(self, source="robot_lift"):
        self.actions = getattr(self, "actions", [])
        self.actions.append(("event_end", source))
        return {"event_label": "hazard", "source": source}

    def stop_session(self, outcome="aborted"):
        self.recording = False
        self.step = None
        self.stopped = True
        return {"message": "saved", "path": "fake.jsonl"}


class FakeGuidedRig:
    def __init__(self, vacuum=(0, 0), pump=0):
        self.vacuum = vacuum
        self.pump = pump
        self.actions = []
        self._poses = {
            "pose1_low": {"q": [1, 2, 3, 4, 5, 6]},
            "pose2_top": {"q": [6, 5, 4, 3, 2, 1]},
        }
        self.current_q = list(self._poses["pose1_low"]["q"])

    def robot_status(self):
        return {
            "reachable": True,
            "robotmode": "Robotmode: RUNNING",
            "safety": "Safetystatus: NORMAL",
        }

    def pose_status(self):
        return {"available": True, "q": list(self.current_q), "tcp": [0, 0, 0.4]}

    def gripper_stats(self, max_age_s=0.0):
        return {
            "vacuum_A_permille": self.vacuum[0],
            "vacuum_B_permille": self.vacuum[1],
            "pump_rpm": self.pump,
        }

    def gripper_action(self, action, channel, vacuum):
        self.actions.append((action, channel, vacuum))
        if action == "grip":
            self.vacuum = (600, 650)
        else:
            self.vacuum = (0, 0)
        return {
            "ok": True,
            "stats": {
                "vacuum_A_permille": self.vacuum[0],
                "vacuum_B_permille": self.vacuum[1],
            },
        }

    def goto_pose(self, name, **kwargs):
        guard = kwargs.get("guard")
        if guard is not None:
            guard()
        self.actions.append(("goto", name))
        self.current_q = list(self._poses[name]["q"])
        return {"pose": name, "completed": True}

    def apply_research_speed_fraction(self, fraction):
        self.actions.append(("speed", fraction))
        return {"applied": True, "status": "applied", "speed_fraction": fraction}


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_integrated_guided_actions_grip_lift_lower_release_and_save():
    state = FakeGuidedState(step=2, distance=2.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock, sleeper=lambda _: None)

    guided.complete_step()
    assert state.step == 3
    assert not rig.actions

    guided.complete_step()
    assert state.step == 5
    assert rig.actions[-1] == ("goto", "pose2_top")
    assert state.actions == [
        ("event_start", "robot_lift"), ("event_end", "robot_lift"),
    ]

    state.step = 8
    result = guided.complete_step()
    assert result["completed"] is True
    assert state.stopped is True
    assert rig.actions[-1] == ("release", "BOTH", 0)


def test_integrated_guided_motion_request_is_accepted_inside_controller_zone():
    state = FakeGuidedState(step=3, distance=1.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    result = guided.complete_step()

    assert result["guided_step"] == 5
    assert rig.actions[-1] == ("goto", "pose2_top")
    assert state.snapshot()["controller_decision"]["speed_fraction"] == 0.0


def test_manual_motion_guard_holds_zero_through_tracking_dropout():
    state = FakeGuidedState(step=3, distance=2.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    guided = GuidedRunController(state, rig)
    original_snapshot = state.snapshot

    def stale_snapshot():
        snap = original_snapshot()
        snap["optitrack_connected"] = False
        snap["controller_decision"] = {
            "command": "protective_stop",
            "speed_fraction": 0.0,
            "output_applied": True,
        }
        return snap

    state.snapshot = stale_snapshot

    guided._manual_motion_guard()

    assert rig.actions == [("speed", 0.0)]


def test_manual_motion_guard_holds_zero_during_rtde_connect_refresh_delay():
    state = FakeGuidedState(step=3, distance=2.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    clock = FakeClock()
    state.controller_updated_at = clock.now - 1.0
    guided = GuidedRunController(state, rig, clock=clock)

    guided._manual_motion_guard()

    assert rig.actions == [("speed", 0.0)]


def test_integrated_guided_weak_seal_stays_on_and_does_not_advance():
    state = FakeGuidedState(step=2, distance=2.0)
    rig = FakeGuidedRig(vacuum=(600, 200))
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    with pytest.raises(ValueError, match="Suction remains on"):
        guided.complete_step()
    assert state.step == 2
    assert not rig.actions
    assert rig.vacuum == (600, 200)


def test_integrated_guided_start_requires_released_low_rig():
    state = FakeGuidedState(step=None, distance=2.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    guided = GuidedRunController(state, rig)

    with pytest.raises(ValueError, match="suction off"):
        guided.start("P01", "T01")
    assert state.recording is False

    rig.vacuum = (0, 0)
    with pytest.raises(ValueError, match="native recording"):
        guided.start("P01", "T01")
    with pytest.raises(ValueError, match="filename"):
        guided.start("P01", "T01", mvn_recording_confirmed=True)
    result = guided.start(
        "P01", "T01", mvn_recording_confirmed=True,
        mvn_recording_reference=r"C:\MVN\P01-T01.mvn")
    assert result["message"] == "recording"
    assert state.recording is True


def test_integrated_guided_physical_action_uses_one_press():
    state = FakeGuidedState(step=2, distance=2.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    result = guided.complete_step(60)

    assert result["guided_step"] == 3
    assert not rig.actions


def test_integrated_guided_old_arm_request_does_not_add_another_press():
    state = FakeGuidedState(step=3, distance=2.0)
    rig = FakeGuidedRig(vacuum=(600, 650))
    clock = FakeClock()
    guided = GuidedRunController(state, rig, clock=clock)

    guided.arm_step()
    clock.advance(5.1)
    state.controller_updated_at = clock.now
    result = guided.complete_step()

    assert result["guided_step"] == 5
    assert rig.actions[-1] == ("goto", "pose2_top")
