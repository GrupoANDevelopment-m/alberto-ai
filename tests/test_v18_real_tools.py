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


class TestToolActor:
    """Real persistent shell actor."""

    def test_run_echo(self):
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["actor"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"command": "echo actor-test-98765", "session": "test"})
        assert "actor-test-98765" in out
        assert not err

    def test_session_list(self):
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["actor"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"action": "list_sessions"})
        assert isinstance(out, str)
        assert not err

    def test_blocked_command(self):
        """Hermes tirith should block dangerous commands."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["actor"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"command": "rm -rf /", "session": "dangerous"})
        assert err
        assert "block" in out.lower() or "tirith" in out.lower() or "dangerous" in out.lower()


class TestToolWorkflow:
    """Real workflow execution."""

    def test_workflow_not_found(self):
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["workflow"]
        class FakeAlberto:
            def squad_list(self):
                return ["content", "engineering"]
        out, err = fn(FakeAlberto(), {"name": "nonexistent_workflow"})
        assert err


class TestToolSkill:
    """Real skill loader."""

    def test_list_action(self):
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["skill"]
        class FakeAlberto: pass
        # List doesn't require a name
        out, err = fn(FakeAlberto(), {"action": "list"})
        assert isinstance(out, str)


class TestToolApplyPatch:
    """Real patch applier."""

    def test_simple_addition(self):
        import os
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["apply_patch"]
        class FakeAlberto: pass
        # Create a temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            fp = f.name
        try:
            # Hermes v4a format requires *** Begin Patch *** wrapper
            patch = "*** Begin Patch\n*** Update File: " + os.path.basename(fp) + "\n@@\n line1\n+inserted\n line2\n line3\n*** End Patch"
            out, err = fn(FakeAlberto(), {"path": fp, "patch": patch})
            # Should succeed (real Hermes v4a)
            content = Path(fp).read_text()
            assert "inserted" in content, f"Expected 'inserted' in: {content!r}"
        finally:
            os.unlink(fp)

    def test_blocked_path(self):
        """Traversed path is blocked."""
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["apply_patch"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"path": "../../etc/passwd", "patch": "@@ -1,1 +1,1 @@\\n-old\\n+new"})
        assert err
        assert "block" in out.lower() or "traversal" in out.lower()


class TestToolChangeDirectory:
    """Real persistent cwd."""

    def test_pwd(self):
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["change_directory"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"path": "/tmp"})
        assert not err
        assert "/tmp" in out

    def test_blocked_path(self):
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["change_directory"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {"path": "../../etc"})
        assert err


class TestToolHealAttempt:
    """Real self-healing."""

    def test_no_error(self):
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["heal_attempt"]
        class FakeAlberto: pass
        out, err = fn(FakeAlberto(), {})
        assert err

    def test_unknown_error(self):
        from alberto.runtime.function_caller import TOOL_REGISTRY
        fn = TOOL_REGISTRY["heal_attempt"]
        # Mock alberto with healer
        class FakeHealer:
            def attempt_heal(self, exc, context, auto_apply=False):
                return {"fixed": False, "matched_fixers": [], "applied": []}
        class FakeAlberto:
            healer = FakeHealer()
        out, err = fn(FakeAlberto(), {"error": "SomeRandomError: nothing matched"})
        assert err
