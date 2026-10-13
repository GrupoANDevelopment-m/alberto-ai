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


def test_shell_tool_fails_closed_without_sandbox(monkeypatch):
    monkeypatch.setattr(
        function_caller.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct host subprocess forbidden")),
    )

    output, is_error = function_caller.tool_run_shell(
        None,
        {"command": "echo should-not-run"},
    )

    assert is_error is True
    assert "sandbox is required" in output


import pytest


@pytest.mark.parametrize("timeout", ["not-a-number", None, 0, -1, 3601, 1.5])
def test_run_shell_rejects_invalid_timeout_without_running(tmp_path, monkeypatch, timeout):
    sandbox = RecordingSandbox(tmp_path)
    output, is_error = function_caller.tool_run_shell(
        SimpleNamespace(sandbox=sandbox),
        {"command": "echo must-not-run", "timeout": timeout},
    )
    assert is_error is True
    assert "invalid timeout" in output
    assert sandbox.calls == []


@pytest.mark.parametrize("timeout", ["invalid", 0, -5, 3601])
def test_bash_rejects_invalid_timeout_without_running(tmp_path, timeout):
    sandbox = RecordingSandbox(tmp_path)
    output, is_error = function_caller.tool_bash(
        SimpleNamespace(sandbox=sandbox),
        {"command": "echo must-not-run", "timeout": timeout},
    )
    assert is_error is True
    assert "invalid timeout" in output
    assert sandbox.calls == []


def test_shell_timeout_accepts_numeric_string(tmp_path, monkeypatch):
    sandbox = RecordingSandbox(tmp_path)
    monkeypatch.setattr("alberto.runtime.audit.log_event", lambda *args, **kwargs: None)
    output, is_error = function_caller.tool_run_shell(
        SimpleNamespace(sandbox=sandbox),
        {"command": "echo safe", "timeout": "11"},
    )
    assert is_error is False
    assert sandbox.calls[0][1] == 11



def test_run_shell_rejects_blocked_command_before_sandbox_execution(tmp_path):
    sandbox = RecordingSandbox(tmp_path)
    output, is_error = function_caller.tool_run_shell(
        SimpleNamespace(sandbox=sandbox),
        {"command": "rm -rf /"},
    )
    assert is_error is True
    assert "BLOCKED" in output
    assert sandbox.calls == []


def test_run_shell_reports_nonzero_exit_as_error(tmp_path, monkeypatch):
    class FailingSandbox(RecordingSandbox):
        def run(self, command, *, timeout=60, cwd=None):
            self.calls.append((command, timeout, cwd))
            return subprocess.CompletedProcess(command, 7, "partial output", "failure detail")

    sandbox = FailingSandbox(tmp_path)
    monkeypatch.setattr("alberto.runtime.audit.log_event", lambda *args, **kwargs: None)
    output, is_error = function_caller.tool_run_shell(
        SimpleNamespace(sandbox=sandbox), {"command": "false"}
    )
    assert is_error is True
    assert "exit_code=7" in output
    assert "failure detail" in output


def test_run_shell_uses_sandbox_home_for_outside_cwd(tmp_path, monkeypatch):
    home = tmp_path / "sandbox-home"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sandbox = RecordingSandbox(home)
    monkeypatch.setattr("alberto.runtime.audit.log_event", lambda *args, **kwargs: None)
    output, is_error = function_caller.tool_run_shell(
        SimpleNamespace(sandbox=sandbox, _cwd=str(outside)),
        {"command": "echo safe"},
    )
    assert is_error is False
    assert sandbox.calls[0][2] == str(home)


def test_run_shell_handles_missing_command(tmp_path):
    sandbox = RecordingSandbox(tmp_path)
    output, is_error = function_caller.tool_run_shell(
        SimpleNamespace(sandbox=sandbox), {"command": ""}
    )
    assert is_error is True
    assert "no command provided" in output
    assert sandbox.calls == []


def test_bash_redacts_detected_secrets_before_returning(tmp_path, monkeypatch):
    sandbox = RecordingSandbox(tmp_path)
    monkeypatch.setattr(
        "alberto.runtime.nemoclaw_real.scan_secrets",
        lambda text: [{"pattern": "api-key"}] if "secret-value" in text else [],
    )
    monkeypatch.setattr(
        "alberto.runtime.nemoclaw_real.redact_secrets",
        lambda text: (text.replace("secret-value", "[REDACTED]"), 1),
    )
    sandbox.run = lambda command, *, timeout=60, cwd=None: subprocess.CompletedProcess(
        command, 0, "secret-value", ""
    )
    output, is_error = function_caller.tool_bash(
        SimpleNamespace(sandbox=sandbox), {"command": "printf secret"}
    )
    assert is_error is False
    assert "[REDACTED]" in output
    assert "secret-value" not in output
    assert "api-key" in output
