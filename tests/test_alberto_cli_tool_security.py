"""Regression tests for the Alberto CLI tool execution boundary."""
import sys
from types import SimpleNamespace

from alberto.runtime import function_caller


def test_cli_tool_uses_argv_without_shell(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(function_caller.subprocess, "run", fake_run)
    output, is_error = function_caller.tool_alberto_cli(None, {"args": "status"})

    assert is_error is False
    assert "ok" in output
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [sys.executable, "-m", "alberto.cli", "status"]
    assert kwargs.get("shell") is False


def test_cli_tool_blocks_shell_command_separators(monkeypatch):
    calls = []
    monkeypatch.setattr(
        function_caller.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    output, is_error = function_caller.tool_alberto_cli(
        None, {"args": "status; echo injected"}
    )

    assert is_error is True
    assert "BLOCKED" in output
    assert calls == []


def test_cli_tool_requires_confirmation_for_mutating_subcommands(monkeypatch):
    calls = []
    monkeypatch.setattr(
        function_caller.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    output, is_error = function_caller.tool_alberto_cli(
        None, {"args": "app create demo \"description\""}
    )

    assert is_error is True
    assert "confirmation" in output.lower()
    assert calls == []


def test_cli_tool_rejects_unbalanced_quotes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        function_caller.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    output, is_error = function_caller.tool_alberto_cli(
        None, {"args": 'status "unterminated'}
    )

    assert is_error is True
    assert "quoting" in output.lower()
    assert calls == []
