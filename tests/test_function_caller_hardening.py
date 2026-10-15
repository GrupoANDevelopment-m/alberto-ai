"""Focused regression tests for shell timeout validation and sandbox routing.

These tests exercise deterministic security boundaries without launching a real shell
or requiring provider credentials.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from alberto.runtime.function_caller import (
    _execute_shell_command,
    _validated_shell_timeout,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (False, None),
        ("not-a-number", None),
        ("1.5", None),
        (1.5, None),
        (0, None),
        (-1, None),
        (3601, None),
        ("30", 30),
        (1, 1),
        (3600, 3600),
    ],
)
def test_validated_shell_timeout_rejects_invalid_or_out_of_range_values(value, expected):
    assert _validated_shell_timeout(value) == expected


def test_validated_shell_timeout_honors_custom_maximum():
    assert _validated_shell_timeout(11, maximum=10) is None
    assert _validated_shell_timeout(10, maximum=10) == 10


def test_execute_shell_command_fails_closed_without_sandbox():
    with pytest.raises(RuntimeError, match="configured sandbox is required"):
        _execute_shell_command(SimpleNamespace(sandbox=None), "echo safe", 10)


@pytest.mark.parametrize(
    "sandbox",
    [
        SimpleNamespace(run=None, home=lambda: "/tmp"),
        SimpleNamespace(run=lambda *a, **k: None, home=None),
    ],
)
def test_execute_shell_command_requires_callable_sandbox_contract(sandbox):
    with pytest.raises(RuntimeError, match="configured sandbox is required"):
        _execute_shell_command(SimpleNamespace(sandbox=sandbox), "echo safe", 10)


def test_execute_shell_command_uses_sandbox_home_by_default(tmp_path):
    calls = []
    home = tmp_path / "home"
    home.mkdir()

    class Sandbox:
        def home(self):
            return str(home)

        def run(self, argv, *, timeout, cwd):
            calls.append((argv, timeout, cwd))
            return "ok"

    result = _execute_shell_command(
        SimpleNamespace(sandbox=Sandbox(), _cwd=None), "printf safe", 7
    )

    assert result == "ok"
    assert calls == [(["bash", "-lc", "printf safe"], 7, str(home.resolve()))]


def test_execute_shell_command_accepts_only_existing_directory_inside_home(tmp_path):
    calls = []
    home = tmp_path / "home"
    nested = home / "nested"
    nested.mkdir(parents=True)

    class Sandbox:
        def home(self):
            return str(home)

        def run(self, argv, *, timeout, cwd):
            calls.append(cwd)
            return "ok"

    _execute_shell_command(
        SimpleNamespace(sandbox=Sandbox(), _cwd=str(nested)), "pwd", 5
    )
    assert calls == [str(nested.resolve())]


def test_execute_shell_command_rejects_path_escape_and_falls_back_to_home(tmp_path):
    calls = []
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()

    class Sandbox:
        def home(self):
            return str(home)

        def run(self, argv, *, timeout, cwd):
            calls.append(cwd)
            return "ok"

    _execute_shell_command(
        SimpleNamespace(sandbox=Sandbox(), _cwd=str(outside)), "pwd", 5
    )
    assert calls == [str(home.resolve())]


def test_execute_shell_command_rejects_nonexistent_working_directory(tmp_path):
    calls = []
    home = tmp_path / "home"
    home.mkdir()

    class Sandbox:
        def home(self):
            return str(home)

        def run(self, argv, *, timeout, cwd):
            calls.append(cwd)
            return "ok"

    _execute_shell_command(
        SimpleNamespace(sandbox=Sandbox(), _cwd=str(home / "missing")), "pwd", 5
    )
    assert calls == [str(home.resolve())]



def test_run_tool_loop_executes_registered_tool_and_continues_with_tool_result():
    import json
    from alberto.runtime.function_caller import run_tool_loop

    tool_call = {
        "id": "call-question-1",
        "type": "function",
        "function": {
            "name": "question",
            "arguments": json.dumps({"question": "Should I continue?"}),
        },
    }
    responses = [
        {"choices": [{"message": {"content": "", "tool_calls": [tool_call]}}]},
        {"choices": [{"message": {"content": "Proceed with the review.", "tool_calls": []}}]},
    ]
    invocations = []

    class Router:
        def invoke(self, task, history, **kwargs):
            invocations.append({"task": task, "history": list(history), "kwargs": kwargs})
            return responses.pop(0)

    result = run_tool_loop(
        SimpleNamespace(router=Router()),
        [{"role": "user", "content": "I need a decision"}],
        max_iterations=3,
    )

    assert result["final_content"] == "Proceed with the review."
    assert result["iterations"] == 2
    assert result["tool_calls"] == [tool_call]
    tool_messages = [message for message in result["history"] if message["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "[question OK]" in tool_messages[0]["content"]
    assert "Should I continue?" in tool_messages[0]["content"]
    assert any(message["role"] == "tool" for message in invocations[1]["history"])
    assert invocations[0]["kwargs"]["tool_choice"] == "auto"


@pytest.mark.parametrize("max_iterations", [0, -1, True, 1.5, "3"])
def test_run_tool_loop_rejects_invalid_iteration_budget_without_calling_router(max_iterations):
    from alberto.runtime.function_caller import run_tool_loop

    calls = []
    router = SimpleNamespace(invoke=lambda *args, **kwargs: calls.append((args, kwargs)))
    result = run_tool_loop(
        SimpleNamespace(router=router), [{"role": "user", "content": "do work"}],
        max_iterations=max_iterations,
    )

    assert result["iterations"] == 0
    assert "positive integer" in result["error"]
    assert calls == []


def test_run_tool_loop_returns_structured_error_for_empty_provider_choices():
    from alberto.runtime.function_caller import run_tool_loop

    router = SimpleNamespace(invoke=lambda *args, **kwargs: {"choices": []})
    result = run_tool_loop(
        SimpleNamespace(router=router), [{"role": "user", "content": "do work"}]
    )

    assert result["iterations"] == 1
    assert "choices must contain an object" in result["error"]
    assert result["tool_calls"] == []


def test_run_tool_loop_surfaces_router_exception_without_losing_contract():
    from alberto.runtime.function_caller import run_tool_loop

    def fail(*args, **kwargs):
        raise RuntimeError("provider offline")

    result = run_tool_loop(
        SimpleNamespace(router=SimpleNamespace(invoke=fail)),
        [{"role": "user", "content": "do work"}],
    )

    assert result["iterations"] == 1
    assert "RuntimeError: provider offline" in result["error"]
    assert result["history"][0]["content"] == "do work"
    assert result["tool_calls"] == []


def test_run_tool_loop_reports_iteration_limit_instead_of_empty_answer():
    import json
    from alberto.runtime.function_caller import run_tool_loop

    call = {
        "id": "call-loop",
        "type": "function",
        "function": {"name": "question", "arguments": json.dumps({"question": "Again?"})},
    }
    router = SimpleNamespace(invoke=lambda *args, **kwargs: {
        "choices": [{"message": {"content": "", "tool_calls": [call]}}]
    })
    result = run_tool_loop(
        SimpleNamespace(router=router), [{"role": "user", "content": "do work"}],
        max_iterations=1,
    )

    assert result["iterations"] == 1
    assert result["final_content"] == "[max iterations reached]"
    assert "max_iterations reached" in result["error"]
