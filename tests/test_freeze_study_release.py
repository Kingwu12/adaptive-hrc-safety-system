from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.freeze_study_release import FROZEN_PATHS, build_freeze


def _study_tree(tmp_path, monkeypatch):
    for relative in FROZEN_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen input\n", encoding="utf-8")
    model_path = tmp_path / "data/models/pilot_hmm.json"
    model_path.write_text(json.dumps({
        "schema_version": 3,
        "states": ["approaching", "working", "retreating"],
        "validation": {
            "method": "leave-one-participant-out",
            "accuracy": 0.82,
            "balanced_accuracy": 0.75,
            "online_filter_accuracy": 0.79,
        },
    }), encoding="utf-8")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    report_path = tmp_path / "qualification.json"
    report_path.write_text(json.dumps({
        "result": "pass",
        "trial_batch": True,
        "captures": [{"model_sha256": model_hash} for _ in range(10)],
    }), encoding="utf-8")

    def fake_run(command, **_kwargs):
        output = "" if command[1] == "status" else "f" * 40 + "\n"
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr("scripts.freeze_study_release.subprocess.run", fake_run)
    return report_path, model_hash


def test_freeze_accepts_clean_qualified_release(tmp_path, monkeypatch):
    report_path, model_hash = _study_tree(tmp_path, monkeypatch)
    payload = build_freeze(tmp_path, report_path)
    assert payload["qualification_capture_count"] == 10
    assert payload["files"]["data/models/pilot_hmm.json"] == model_hash
    assert payload["git_commit"] == "f" * 40


def test_freeze_rejects_model_not_used_by_qualification_runs(tmp_path, monkeypatch):
    report_path, _model_hash = _study_tree(tmp_path, monkeypatch)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for capture in report["captures"]:
        capture["model_sha256"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="not recorded with the active model"):
        build_freeze(tmp_path, report_path)
