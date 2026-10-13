"""Regression tests for Hermes execution tools using the configured sandbox."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

from alberto.engines import hermes_tools


class RecordingSandbox:
    def __init__(self, home):
        self._home = Path(home)
        self.writes = []
        self.calls = []

    def home(self):
        return self._home

    def write(self, path, content):
        self.writes.append((Path(path), content))

    def run(self, command, *, timeout=60, cwd=None):
        self.calls.append((command, timeout, cwd))
        if command and command[0] == "rm":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "sandbox output\n", "")


def test_terminal_tool_routes_command_through_sandbox(tmp_path, monkeypatch):
    sandbox = RecordingSandbox(tmp_path)
    monkeypatch.setattr(
        hermes_tools,
        "_try_import",
        lambda name: (_ for _ in ()).throw(AssertionError("must not bypass configured sandbox")),
    )

    result = hermes_tools.tool_terminal(
        SimpleNamespace(sandbox=sandbox),
        {"command": "printf safe", "timeout": 12},
    )

    assert result["ok"] is True
    assert result["stdout"] == "sandbox output\n"
    assert sandbox.calls == [(["bash", "-lc", "printf safe"], 12, tmp_path)]


def test_code_execution_writes_and_runs_python_inside_sandbox(tmp_path, monkeypatch):
    sandbox = RecordingSandbox(tmp_path)
    monkeypatch.setattr(
        hermes_tools,
        "_try_import",
        lambda name: (_ for _ in ()).throw(AssertionError("must not bypass configured sandbox")),
    )
    monkeypatch.setattr(hermes_tools.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("direct subprocess forbidden")))

    result = hermes_tools.tool_code_execution(
        SimpleNamespace(sandbox=sandbox),
        {"code": "print('hello')", "language": "python", "timeout": 15},
    )

    assert result["ok"] is True
    assert sandbox.writes and sandbox.writes[0][1] == "print('hello')"
    command, timeout, cwd = sandbox.calls[0]
    assert command[0] != "rm"
    assert command[1].endswith(".py")
    assert timeout == 15
    assert cwd == tmp_path
    assert sandbox.calls[-1][0][:2] == ["rm", "-f"]


def test_code_execution_refuses_without_sandbox():
    result = hermes_tools.tool_code_execution(SimpleNamespace(), {"code": "print('hello')"})

    assert result["ok"] is False
    assert "sandbox is required" in result["error"]


def test_terminal_reports_nonzero_exit_as_failure(tmp_path):
    class FailedSandbox(RecordingSandbox):
        def run(self, command, *, timeout=60, cwd=None):
            self.calls.append((command, timeout, cwd))
            return subprocess.CompletedProcess(command, 2, "", "failed")

    sandbox = FailedSandbox(tmp_path)
    result = hermes_tools.tool_terminal(
        SimpleNamespace(sandbox=sandbox),
        {"command": "false"},
    )

    assert result["ok"] is False
    assert result["returncode"] == 2
