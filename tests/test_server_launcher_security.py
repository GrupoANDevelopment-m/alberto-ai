"""Security tests for the watchdog launcher's PID-file handling."""
import importlib.util
import os
import stat
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "alberto-serve"
SPEC = importlib.util.spec_from_file_location("alberto_serve_launcher", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_write_lock_creates_private_regular_file(tmp_path):
    path = tmp_path / "server.pid"
    launcher.write_lock(path, os.getpid())
    info = path.stat()
    assert stat.S_ISREG(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert path.read_text() == str(os.getpid())


def test_write_lock_refuses_symlink_target(tmp_path):
    target = tmp_path / "important.txt"
    target.write_text("preserve")
    path = tmp_path / "server.pid"
    path.symlink_to(target)
    with pytest.raises(OSError):
        launcher.write_lock(path, os.getpid())
    assert target.read_text() == "preserve"


def test_check_lock_treats_symlink_pid_file_as_unsafe(tmp_path):
    target = tmp_path / "pid-source"
    target.write_text(str(os.getpid()))
    path = tmp_path / "server.pid"
    path.symlink_to(target)
    assert launcher.check_lock(path) is True
    assert target.read_text() == str(os.getpid())


def test_kill_existing_refuses_to_kill_non_alberto_process(tmp_path):
    path = tmp_path / "server.pid"
    path.write_text(str(os.getppid()))
    path.chmod(0o600)
    with pytest.raises(RuntimeError, match="does not point to an Alberto server"):
        launcher.kill_alberto_serves(path)
