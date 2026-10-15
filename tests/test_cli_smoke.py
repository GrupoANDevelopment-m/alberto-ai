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
