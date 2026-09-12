from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_powershell_launcher_failure_paths():
    runtime = os.environ.get("HRC_TEST_PWSH") or shutil.which("pwsh") or shutil.which("powershell")
    if runtime is None:
        pytest.skip("PowerShell required; set HRC_TEST_PWSH to a portable runtime")
    result = subprocess.run(
        [runtime, "-NoLogo", "-NoProfile", "-File",
         str(ROOT / "tests" / "test_windows_launcher.ps1"),
         "-LauncherPath", str(ROOT / "Start-Lab.ps1")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LAUNCHER CHECKS PASSED" in result.stdout
