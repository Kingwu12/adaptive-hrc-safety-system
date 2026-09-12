from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.dashboard_server import SERVICE_CONTRACT, service_identity


ROOT = Path(__file__).resolve().parents[1]


def test_backend_identity_binds_process_to_loaded_source():
    identity = service_identity()
    source = ROOT / "scripts" / "dashboard_server.py"

    assert identity["contract"] == SERVICE_CONTRACT
    assert identity["pid"] > 0
    assert identity["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_cmd_launcher_bypasses_policy_only_for_child_process():
    launcher = (ROOT / "Start-Lab.cmd").read_text(encoding="utf-8")

    assert "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass" in launcher
    assert '"%~dp0Start-Lab.ps1"' in launcher
    assert "Set-ExecutionPolicy" not in launcher


def test_launcher_requires_source_proof_and_protects_active_trials():
    launcher = (ROOT / "Start-Lab.ps1").read_text(encoding="utf-8")

    assert "source_sha256" in launcher
    assert "Get-FileHash -Algorithm SHA256" in launcher
    assert "if ($labTrialActive)" in launcher
    assert "The launcher will not kill it" in launcher
    assert "LAB READY" in launcher
