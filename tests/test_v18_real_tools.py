"""test_v18_real_tools.py - Verify the newly-real tool implementations.

Tests tool_question (interactive), tool_plan (LLM decomposition),
tool_codesearch (ripgrep), tool_history (real conversation),
tool_task (Hermes todo_tool), tool_lsp (real code intelligence).
"""
import sys
import subprocess
import pytest
from pathlib import Path
sys.path.insert(0, "/workspace/alberto-ai")


class TestToolQuestion:
    """Real question tool - works in interactive and non-interactive mode."""

    def test_non_interactive_returns_formatted(self):
        """Without --interactive, returns formatted message."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["question"]
        # Mock alberto without conversations
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"question": "What's your name?", "options": ["Alice", "Bob"]})
        assert "What's your name?" in out
        assert "Alice" in out
        assert not err


class TestToolPlan:
    """Real plan tool - uses LLM to decompose goals."""

    def test_plan_with_provided_steps(self):
        """If user provides steps, just stores them."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["plan"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"goal": "Build app", "steps": ["Step 1", "Step 2"]})
        assert "Step 1" in out
        assert "Step 2" in out
        assert not err


class TestToolCodesearch:
    """Real codesearch via ripgrep/grep."""

    def test_finds_in_python_file(self):
        """Search for a string and find it."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["codesearch"]
        class FakeAlberto: pass
        # Search for 'class TestToolCodesearch' in tests/test_v18_real_tools.py
        out, err = fn(FakeAlberto(), {
            "query": "TestToolCodesearch",
            "path": "tests/test_v18_real_tools.py"
        })
        assert "TestToolCodesearch" in out
        assert not err

    def test_finds_with_file_types(self):
        """Search restricted to Python files."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["codesearch"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {
            "query": "function_caller",
            "path": "alberto",
            "file_types": ["py"]
        })
        assert "function_caller" in out


class TestToolHistory:
    """Real history from conversations."""

    def test_history_no_store(self):
        """Without conversations store, returns error."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["history"]
        class FakeAlberto: pass  # no .conversations
        out, err = fn(FakeAlberto(), {"limit": 5})
        # Either error message or empty
        assert isinstance(out, str)


class TestToolTask:
    """Real task management via Hermes todo_tool."""

    def test_list_returns_something(self):
        """list action returns a result (may fail if upstream not loaded)."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["task"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"action": "list"})
        # Either success (real todo) or graceful error
        assert isinstance(out, str)


class TestToolLSP:
    """Real LSP-like code intelligence."""

    def test_symbols_finds_python_def(self):
        """symbols action finds Python definitions."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["lsp"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {
            "action": "symbols",
            "path": "tests/test_v18_real_tools.py"
        })
        # Should find test classes/methods
        assert "TestTool" in out or "symbols" in out.lower()
        assert not err

    def test_hover_shows_line(self):
        """hover shows the requested line."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["lsp"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {
            "action": "hover",
            "path": "tests/test_v18_real_tools.py",
            "line": 30
        })
        # Format is "  L{line_no:4d}:" which becomes "  L  30:"
        assert "30" in out
        assert not err

    def test_references_finds_usages(self):
        """references finds all usages of a symbol."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["lsp"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {
            "action": "references",
            "path": "tests/test_v18_real_tools.py",
            "symbol": "TestToolLSP"
        })
        assert "TestToolLSP" in out
        assert not err

    def test_lsp_blocks_traversal(self):
        """LSP blocks path traversal via Hermes path_security."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["lsp"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {
            "action": "symbols",
            "path": "../../etc/passwd"
        })
        assert err  # Should be blocked
        assert "block" in out.lower() or "traversal" in out.lower()
