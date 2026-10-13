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
