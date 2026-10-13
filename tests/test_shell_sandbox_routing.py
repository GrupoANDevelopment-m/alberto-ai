"""Regression tests ensuring shell tools honor the configured sandbox."""
from pathlib import Path
from types import SimpleNamespace
import subprocess

from alberto.runtime import function_caller


class RecordingSandbox:
    def __init__(self, home):
        self._home = Path(home)
        self.calls = []

    def home(self):
        return self._home

    def run(self, command, *, timeout=60, cwd=None):
        self.calls.append((command, timeout, cwd))
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout="sandbox output", stderr=""
        )


def test_run_shell_uses_configured_sandbox(tmp_path, monkeypatch):
    sandbox = RecordingSandbox(tmp_path)
    monkeypatch.setattr("alberto.runtime.audit.log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("alberto.runtime.audit.log_blocked_shell", lambda *args, **kwargs: None)

    output, is_error = function_caller.tool_run_shell(
        SimpleNamespace(sandbox=sandbox),
        {"command": "echo safe", "timeout": 7},
    )

    assert is_error is False
    assert "sandbox output" in output
    assert sandbox.calls == [(["bash", "-lc", "echo safe"], 7, str(tmp_path))]


def test_bash_uses_configured_sandbox(tmp_path):
    sandbox = RecordingSandbox(tmp_path)

    output, is_error = function_caller.tool_bash(
        SimpleNamespace(sandbox=sandbox),
        {"command": "printf safe", "timeout": 9},
    )

    assert is_error is False
    assert "sandbox output" in output
    assert sandbox.calls == [(["bash", "-lc", "printf safe"], 9, str(tmp_path))]
