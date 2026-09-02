from types import SimpleNamespace

from scripts.vg10 import VG10


def test_vg10_reports_ssh_failure_instead_of_empty_success(monkeypatch):
    failed = SimpleNamespace(returncode=255, stdout="", stderr="host key verification failed")
    monkeypatch.setattr("scripts.vg10.subprocess.run", lambda *args, **kwargs: failed)

    result = VG10().stats()

    assert result == {"ok": False, "error": "host key verification failed"}


def test_vg10_reports_empty_agent_output(monkeypatch):
    empty = SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr("scripts.vg10.subprocess.run", lambda *args, **kwargs: empty)

    result = VG10().stats()

    assert result == {"ok": False, "error": "robot SSH agent returned no output"}
