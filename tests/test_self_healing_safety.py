"""Regression tests for bounded self-healing side effects."""
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from alberto.runtime.self_healing import SelfHealer


def make_healer(alberto):
    healer = SelfHealer.__new__(SelfHealer)
    healer.alberto = alberto
    return healer


def test_stale_lock_cleanup_only_removes_old_regular_locks_under_memory_home(tmp_path, monkeypatch):
    home = tmp_path / "mimo"
    home.mkdir()
    old_lock = home / "old.lock"
    fresh_lock = home / "fresh.lock"
    external_lock = tmp_path / "external.lock"
    symlink_lock = home / "external.lock"

    old_lock.write_text("old", encoding="utf-8")
    fresh_lock.write_text("fresh", encoding="utf-8")
    external_lock.write_text("external", encoding="utf-8")
    symlink_lock.symlink_to(external_lock)

    monkeypatch.setattr(time, "time", lambda: 1000.0)
    os.utime(old_lock, (100.0, 100.0))
    os.utime(fresh_lock, (980.0, 980.0))
    os.utime(external_lock, (100.0, 100.0))

    healer = make_healer(SimpleNamespace(mimo=SimpleNamespace(_home=home)))
    result = healer._fix_stale_lock("stale lock", "")

    assert result["ok"] is True
    assert not old_lock.exists()
    assert fresh_lock.exists()
    assert external_lock.exists()
    assert symlink_lock.is_symlink()


def test_permission_repair_targets_one_path_inside_sandbox(tmp_path):
    target = tmp_path / "locked.txt"
    target.write_text("content", encoding="utf-8")

    class FakeSandbox:
        def __init__(self):
            self.calls = []

        def home(self):
            return tmp_path

        def run(self, command, *, timeout=60, cwd=None):
            self.calls.append((command, timeout, cwd))
            return subprocess.CompletedProcess(command, 0, "", "")

    sandbox = FakeSandbox()
    healer = make_healer(SimpleNamespace(
        sandbox=sandbox,
        mimo=SimpleNamespace(_home=tmp_path),
    ))

    result = healer._fix_permission_denied(
        f"Permission denied: '{target}'",
        "",
    )

    assert result["ok"] is True
    assert sandbox.calls == [(["chmod", "u+rwX", str(target)], 10, str(tmp_path))]
    assert "-R" not in sandbox.calls[0][0]


def test_permission_repair_refuses_paths_outside_sandbox(tmp_path):
    class FakeSandbox:
        def __init__(self):
            self.calls = []

        def home(self):
            return tmp_path

        def run(self, command, **kwargs):
            self.calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

    sandbox = FakeSandbox()
    healer = make_healer(SimpleNamespace(
        sandbox=sandbox,
        mimo=SimpleNamespace(_home=tmp_path),
    ))

    result = healer._fix_permission_denied("Permission denied: '/etc/passwd'", "")

    assert result["ok"] is False
    assert sandbox.calls == []


def test_server_crash_repair_never_kills_processes(monkeypatch):
    healer = make_healer(SimpleNamespace())
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))

    result = healer._fix_server_crash("server crashed", ctx="manual")

    assert result["ok"] is False
    assert "pkill" not in str(calls)
    assert calls == []


def test_server_watchdog_owns_restart_lifecycle():
    healer = make_healer(SimpleNamespace())

    result = healer._fix_server_crash("server crashed", ctx="server_watchdog")

    assert result["ok"] is True
    assert "watchdog" in result["action"]
