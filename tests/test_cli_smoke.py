"""test_cli_smoke.py - Smoke tests for ALL alberto CLI subcommands.

Closes G-T1 (CLI 0% testada).
"""
import os
import sys
import subprocess
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pytest


# Disable LLM calls during CI
os.environ.setdefault("NVIDIA_API_KEY", "test-key-disabled")


SUBCOMMANDS = [
    ("banner", []),
    ("status", []),
    ("tools", []),
    ("squad", []),
    ("skill", ["list"]),
    ("memory", ["list"]),
    ("model", []),
    ("router", []),
    ("security", ["patterns"]),
]


class TestCLIAllSubcommands:
    """Smoke test for all CLI subcommands - closes G-T1."""

    @pytest.mark.parametrize("subcommand,args", SUBCOMMANDS)
    def test_subcommand_runs_without_error(self, subcommand, args):
        """Each subcommand should at least return with exit code 0 or 2 (arg error)."""
        # Run alberto cli directly via python module
        # Use a temporary LLM key to avoid real network calls
        env = os.environ.copy()
        env["ALBERTO_OFFLINE"] = "1"  # Hint to skip LLM calls

        proc = subprocess.run(
            [sys.executable, "-m", "alberto.cli", subcommand] + args,
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=10,
            env=env,
        )
        # 0 = OK, 2 = argparse error (acceptable for subcommands needing args)
        assert proc.returncode in (0, 2), (
            f"alberto {subcommand} failed: {proc.stderr.decode()[:300]}"
        )

    def test_help_message(self):
        """`alberto --help` should print available subcommands."""
        proc = subprocess.run(
            [sys.executable, "-m", "alberto.cli", "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=10,
        )
        assert proc.returncode == 0
        out = proc.stdout.decode()
        # Should list at least chat, status, tools
        assert "chat" in out
        assert "status" in out
        assert "tools" in out


class TestCLIHandlersInProcess:
    def test_memory_handler_set_get_search_and_list(self, capsys):
        from types import SimpleNamespace
        from alberto.cli import cmd_memory

        class FakeAlberto:
            def __init__(self):
                self.values = {"alpha": "value"}
            def memory_set(self, key, value):
                self.values[key] = value
            def memory_get(self, key):
                return self.values.get(key)
            def memory_search(self, query):
                return [{"key": "alpha", "value": self.values["alpha"]}]
            def memory_list(self):
                return [{"key": key, "value": value} for key, value in self.values.items()]

        alberto = FakeAlberto()
        assert cmd_memory(SimpleNamespace(action="set", key="beta", value="two"), alberto) == 0
        assert "ok: beta" in capsys.readouterr().out
        assert cmd_memory(SimpleNamespace(action="get", key="missing"), alberto) == 0
        assert "(not found)" in capsys.readouterr().out
        assert cmd_memory(SimpleNamespace(action="search", query="alpha"), alberto) == 0
        assert "[alpha] value" in capsys.readouterr().out
        assert cmd_memory(SimpleNamespace(action="list"), alberto) == 0
        assert "[beta] two" in capsys.readouterr().out

    def test_ask_handler_reports_response_and_tool_calls(self, capsys):
        from types import SimpleNamespace
        from alberto.cli import cmd_ask

        class FakeAlberto:
            def chat(self, prompt):
                assert prompt == "hello"
                return {
                    "strategy": "solo",
                    "response": "world",
                    "tool_calls": [{"tool": "read", "result": "file content"}],
                }

        assert cmd_ask(SimpleNamespace(prompt="hello"), FakeAlberto()) == 0
        output = capsys.readouterr().out
        assert "[strategy] solo" in output
        assert "[response] world" in output
        assert "[tool] read: file content" in output

    def test_model_test_handler_returns_nonzero_when_unconfigured(self, capsys):
        from types import SimpleNamespace
        from alberto.cli import cmd_model

        class FakeAlberto:
            def model_test(self, task):
                return None

        assert cmd_model(SimpleNamespace(action="test", task="chat"), FakeAlberto()) == 1
        assert "no model configured" in capsys.readouterr().out



def test_cli_model_test_never_prints_api_secret(capsys):
    from types import SimpleNamespace
    from alberto.cli import cmd_model

    secret = "super-secret-api-key"

    class FakeAlberto:
        def model_test(self, task):
            assert task == "chat"
            return {"OPENAI_API_KEY": secret, "LLM_MODEL": "test-model"}

    assert cmd_model(SimpleNamespace(action="test", task="chat"), FakeAlberto()) == 0
    output = capsys.readouterr().out
    assert secret not in output
    assert "OPENAI_API_KEY=***" in output



@pytest.mark.parametrize(
    ("argv", "handler_name", "expected"),
    [
        (
            ["memory", "set", "project.goal", "Ship", "safe", "app"],
            "cmd_memory",
            {"action": "set", "key": "project.goal", "value": "Ship safe app"},
        ),
        (
            ["model", "set", "chat", "openrouter", "openai/gpt-4o-mini",
             "https://openrouter.ai/api", "OPENROUTER_API_KEY"],
            "cmd_model",
            {"action": "set", "task": "chat", "provider": "openrouter",
             "model_id": "openai/gpt-4o-mini", "base_url": "https://openrouter.ai/api",
             "cred_env": "OPENROUTER_API_KEY"},
        ),
        (
            ["squad", "run", "engineering", "Build", "the", "app"],
            "cmd_squad",
            {"action": "run", "name": "engineering", "prompt": "Build the app"},
        ),
        (
            ["s", "add", "reviewer", "Review", "this", "diff"],
            "cmd_shortcut",
            {"action": "add", "key": "reviewer", "expansion": "Review this diff"},
        ),
        (
            ["hermes", "exec", "print('hello", "world')"],
            "cmd_hermes",
            {"action": "exec", "code": "print('hello world')"},
        ),
    ],
)
def test_main_parses_and_maps_positional_arguments(monkeypatch, argv, handler_name, expected):
    from alberto import cli

    captured = {}

    class FakeAlberto:
        def shutdown(self):
            captured["shutdown"] = True

    monkeypatch.setattr(cli, "_get_alberto", lambda: FakeAlberto())

    def capture(args, _agent):
        captured.update(vars(args))
        return 0

    monkeypatch.setattr(cli, handler_name, capture)

    assert cli.main(argv) == 0
    assert all(captured.get(key) == value for key, value in expected.items())
    assert captured["shutdown"] is True


@pytest.mark.parametrize(
    "argv",
    [
        ["memory", "set", "key"],
        ["model", "set", "chat", "provider"],
        ["model", "test"],
        ["squad", "run", "engineering"],
        ["s", "add", "reviewer"],
        ["hermes", "browser"],
        ["hermes", "exec"],
    ],
)
def test_main_rejects_incomplete_commands_before_agent_initialization(monkeypatch, argv):
    from alberto import cli

    monkeypatch.setattr(
        cli, "_get_alberto",
        lambda: pytest.fail("agent must not initialize for invalid CLI arguments"),
    )
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_main_empty_argv_does_not_fall_back_to_process_arguments(monkeypatch):
    from alberto import cli

    monkeypatch.setattr(
        cli, "_get_alberto",
        lambda: pytest.fail("agent must not initialize when argparse has no command"),
    )
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_mcp_call_reports_invalid_json_without_invoking_server(capsys):
    from types import SimpleNamespace
    from alberto.cli import cmd_mcp

    class MCP:
        def call(self, *args):
            pytest.fail("MCP call must not run when arguments are invalid JSON")

    args = SimpleNamespace(mcp_action="call", mcp_args=["server", "tool", "{invalid"])
    assert cmd_mcp(args, SimpleNamespace(mcp=MCP())) == 1
    assert "invalid JSON tool arguments" in capsys.readouterr().err
