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


def test_memory_pruning_writes_private_backup_before_deleting(tmp_path):
    import json
    import stat

    entries = [
        {"key": f"memory-{index}", "value": f"value-{index}", "updated_at": index}
        for index in range(101)
    ]
    deleted = []

    class FakeMimo:
        _home = tmp_path / "mimo"

        def memory_list(self):
            return list(entries)

        def memory_delete(self, key):
            deleted.append(key)

    healer = make_healer(SimpleNamespace(mimo=FakeMimo()))
    healer.heal_log = tmp_path / ".mimo" / "heal_log.json"

    result = healer._fix_memory_leak("memory leak", "")

    assert result["ok"] is True
    assert result["removed"] == 51
    assert len(deleted) == 51
    backup = Path(result["backup"])
    assert backup.exists()
    assert len(json.loads(backup.read_text(encoding="utf-8"))) == 101
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_import_error_auto_install_uses_allowlist(monkeypatch):
    from alberto.runtime import self_healing

    calls = []
    monkeypatch.setattr(self_healing, "_pip_install", lambda package: calls.append(package) or (True, "ok"))
    healer = make_healer(SimpleNamespace())

    result = healer._fix_import_error("ModuleNotFoundError: No module named 'yaml'", "")

    assert result["ok"] is True
    assert result["package"] == "pyyaml"
    assert calls == ["pyyaml"]


def test_import_error_blocks_unapproved_package_install(monkeypatch):
    from alberto.runtime import self_healing

    calls = []
    monkeypatch.setattr(self_healing, "_pip_install", lambda package: calls.append(package) or (True, "ok"))
    healer = make_healer(SimpleNamespace())

    result = healer._fix_import_error("ModuleNotFoundError: No module named 'unapproved_payload'", "")

    assert result["ok"] is False
    assert "allowlist" in result["reason"]
    assert calls == []



def test_rate_limit_recovery_reports_missing_alternative_model(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    healer = make_healer(SimpleNamespace(router=SimpleNamespace(
        config=SimpleNamespace(tasks=[])
    )))
    result = healer._fix_rate_limit("429 rate limit", "")
    assert result == {
        "fix": "rate_limit", "ok": False, "reason": "no alternative model"
    }


def test_rate_limit_recovery_uses_configured_task_fallback(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    healer = make_healer(SimpleNamespace(router=SimpleNamespace(
        config=SimpleNamespace(tasks={"chat": "provider/model"})
    )))
    result = healer._fix_rate_limit("429 rate limit", "")
    assert result["ok"] is True
    assert "next turn" in result["action"]


def test_corrupt_database_recovery_keeps_private_backup(tmp_path):
    db_home = tmp_path / "mimo"
    db_home.mkdir()
    db = db_home / "memory.db"
    db.write_bytes(b"corrupt-database")

    class Mimo:
        _home = db_home

        def __init__(self):
            self.reinitialized = False

        def _init_db(self):
            self.reinitialized = True

    mimo = Mimo()
    healer = make_healer(SimpleNamespace(mimo=mimo))
    result = healer._fix_corrupt_db("database is malformed", "")

    assert result["ok"] is True
    assert Path(result["backup"]).read_bytes() == b"corrupt-database"
    assert not db.exists()
    assert mimo.reinitialized is True


def test_corrupt_database_recovery_refuses_when_database_is_missing(tmp_path):
    home = tmp_path / "mimo"
    home.mkdir()
    healer = make_healer(SimpleNamespace(mimo=SimpleNamespace(_home=home)))
    result = healer._fix_corrupt_db("database is malformed", "")
    assert result["ok"] is False
    assert "no db found" in result["reason"]


def test_backoff_recovery_fixers_are_deterministic_without_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))
    healer = make_healer(SimpleNamespace())
    api = healer._fix_api_5xx("503 Service Unavailable", "")
    network = healer._fix_network_unreachable("network is unreachable", "")

    assert api["ok"] is True and api["fix"] == "api_5xx"
    assert network["ok"] is True and network["fix"] == "network_unreachable"
    assert sleeps == [1, 2]
