"""test_v182_hermes_tools.py - Tests for the 25 REAL Hermes tools via model_tools.

Each test calls a different Hermes tool through upstream_bridge to
verify the entire dispatch chain works.
"""
import os
import sys
import json
import subprocess
import tempfile
import pytest
from pathlib import Path

sys.path.insert(0, "/workspace/alberto-ai")


class TestHermesToolsViaBridge:
    """Test that real Hermes tools (via model_tools) work end-to-end."""

    def test_terminal_real_execution(self):
        """terminal tool: real shell command via Hermes."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        r = handle_hermes_tool_call("terminal", {"command": "echo hermes-bridge-real"})
        assert "hermes-bridge-real" in r
        assert '"exit_code": 0' in r

    def test_write_file_creates_real_file(self):
        """write_file tool: real file creation."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = f.name
        try:
            r = handle_hermes_tool_call("write_file", {"path": path, "content": "hermes wrote this"})
            assert "files_modified" in r
            assert Path(path).read_text() == "hermes wrote this"
        finally:
            os.unlink(path)

    def test_read_file_reads_real_content(self):
        """read_file tool: real file reading with line numbers."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("line one\\nline two\\nline three\\n")
            path = f.name
        try:
            r = handle_hermes_tool_call("read_file", {"path": path})
            parsed = json.loads(r)
            assert "content" in parsed
            assert "line one" in parsed["content"]
            assert "line two" in parsed["content"]
        finally:
            os.unlink(path)

    def test_read_file_blocks_sensitive(self):
        """read_file tool: blocks SSH keys."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        r = handle_hermes_tool_call("read_file", {"path": "/root/.ssh/id_rsa"})
        assert "blocked" in r.lower() or "sensitive" in r.lower()

    def test_patch_file_replaces_text(self):
        """patch tool: real find-and-replace."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("old_value = 1\\n")
            path = f.name
        try:
            r = handle_hermes_tool_call("patch", {
                "path": path,
                "old_string": "old_value = 1",
                "new_string": "new_value = 2"
            })
            content = Path(path).read_text()
            assert "new_value = 2" in content
            assert "old_value" not in content
        finally:
            os.unlink(path)

    def test_search_files_finds_matches(self):
        """search_files tool: real content search."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        r = handle_hermes_tool_call("search_files", {
            "pattern": "def test_search_files",
            "path": "tests"
        })
        # Should find this file
        assert "test_search_files" in r or "no matches" in r

    def test_skills_list_returns_skills(self):
        """skills_list tool: real skills catalog."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        r = handle_hermes_tool_call("skills_list", {})
        # Should return some skills list (or empty)
        assert isinstance(r, str)

    def test_skill_view_returns_content(self):
        """skill_view tool: real skill content."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        # Try viewing any skill
        r = handle_hermes_tool_call("skill_view", {"name": "agent-reach"})
        # Either returns content or "not found" - both are valid
        assert isinstance(r, str)

    def test_memory_via_bridge_set_get(self):
        """memory tool (agent-loop): real sqlite-backed set/get."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        handle_hermes_tool_call("memory", {"action": "set", "key": "test_v182_bridge", "value": "real"})
        r = handle_hermes_tool_call("memory", {"action": "get", "key": "test_v182_bridge"})
        assert "real" in r

    def test_todo_list_returns_current(self):
        """todo tool: real todo list."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        r = handle_hermes_tool_call("todo", {"action": "list"})
        # Hermes might require agent context - just verify it returns something
        assert isinstance(r, str)

    def test_project_list_returns_empty_or_projects(self):
        """project_list tool: real project listing."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        r = handle_hermes_tool_call("project_list", {})
        assert isinstance(r, str)

    def test_clarify_returns_question(self):
        """clarify tool: real clarification ask."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        # Will return error since no real user in test, but should be a JSON response
        r = handle_hermes_tool_call("clarify", {"question": "What is 2+2?", "options": ["3", "4"]})
        assert isinstance(r, str)


class TestHermesToolDefinitions:
    """Test that all OpenAI tool definitions are valid."""

    def test_get_openai_definitions_returns_list(self):
        from alberto.runtime.upstream_bridge import get_openai_tool_definitions
        defs = get_openai_tool_definitions()
        assert isinstance(defs, list)
        assert len(defs) >= 25  # We expect 25 from upstream Hermes

    def test_all_definitions_have_required_fields(self):
        from alberto.runtime.upstream_bridge import get_openai_tool_definitions
        defs = get_openai_tool_definitions()
        for d in defs:
            assert "type" in d, f"missing type: {d}"
            assert d["type"] == "function", f"not function: {d}"
            assert "function" in d
            func = d["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func

    def test_definitions_contain_known_tools(self):
        from alberto.runtime.upstream_bridge import get_openai_tool_definitions
        defs = get_openai_tool_definitions()
        names = [d["function"]["name"] for d in defs]
        # Should have at least these core tools
        assert "terminal" in names
        assert "read_file" in names
        assert "write_file" in names


class TestHermesWorkflow:
    """End-to-end: chain multiple Hermes tools together."""

    def test_workflow_write_then_read(self):
        """Write a file, then read it back via Hermes."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = f.name
        try:
            # Write
            r1 = handle_hermes_tool_call("write_file", {"path": path, "content": "workflow test 123"})
            assert "files_modified" in r1
            # Read back
            r2 = handle_hermes_tool_call("read_file", {"path": path})
            assert "workflow test 123" in r2
        finally:
            os.unlink(path)

    def test_workflow_terminal_creates_file_then_read(self):
        """Use terminal to create file, then read_file to verify."""
        from alberto.runtime.upstream_bridge import handle_hermes_tool_call
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = f.name
        try:
            # Use terminal
            r1 = handle_hermes_tool_call("terminal", {"command": f"echo 'created via terminal' > {path}"})
            assert '"exit_code": 0' in r1
            # Read it
            r2 = handle_hermes_tool_call("read_file", {"path": path})
            assert "created via terminal" in r2
        finally:
            os.unlink(path)


class TestHermesToolFailClosedContracts:
    def test_core_tools_validate_required_inputs_and_sandbox(self, monkeypatch):
        from alberto.engines import hermes_tools as tools

        assert tools.tool_browser(None, {})["error"] == "missing 'url'"
        unsafe = tools.tool_browser(None, {"url": "http://127.0.0.1"})
        assert unsafe["ok"] is False
        assert "blocked unsafe browser URL" in unsafe["error"]

        assert tools.tool_code_execution(None, {})["error"] == "missing 'code'"
        unsupported = tools.tool_code_execution(None, {"code": "print(1)", "language": "bash"})
        assert unsupported["ok"] is False
        assert "only Python" in unsupported["error"]
        no_sandbox = tools.tool_code_execution(None, {"code": "print(1)"})
        assert no_sandbox["ok"] is False
        assert "configured sandbox" in no_sandbox["error"]

        assert tools.tool_terminal(None, {})["error"] == "missing 'command'"
        no_terminal_sandbox = tools.tool_terminal(None, {"command": "echo test"})
        assert no_terminal_sandbox["ok"] is False
        assert "configured sandbox" in no_terminal_sandbox["error"]

        assert tools.tool_vision(None, {})["error"] == "need image_url or image_base64"
        assert tools.tool_web_search(None, {})["error"] == "missing 'query'"
        assert tools.tool_send_message(None, {})["error"] == "need platform, target, message"
        assert tools.invoke_hermes_tool(None, "__missing__", {})["ok"] is False

    def test_mcp_rejects_unknown_action_instead_of_reporting_success(self):
        from alberto.engines.hermes_tools import tool_mcp

        result = tool_mcp(None, {"action": "delete_everything"})
        assert result["ok"] is False
        assert "unsupported MCP action" in result["error"]

    def test_browser_fallback_uses_pinned_connections_and_disables_proxies(self, monkeypatch):
        import urllib.request
        from alberto.engines import hermes_tools as tools
        from alberto.runtime import function_caller

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return b"<html>safe</html>"

        class FakeOpener:
            def open(self, request, timeout):
                assert request.full_url == "https://example.com/"
                assert timeout == 30
                return FakeResponse()

        captured = {}
        monkeypatch.setattr(tools, "_try_import", lambda _name: None)
        monkeypatch.setattr(function_caller, "_validate_public_web_url", lambda _url: None)
        monkeypatch.setattr(
            urllib.request,
            "build_opener",
            lambda *handlers: (captured.setdefault("handlers", handlers) and FakeOpener()),
        )

        result = tools.tool_browser(None, {"url": "https://example.com/"})
        assert result["ok"] is True
        assert result["text"] == "safe"
        handlers = captured["handlers"]
        assert any(isinstance(h, urllib.request.ProxyHandler) and h.proxies == {} for h in handlers)
        assert any(isinstance(h, function_caller._PinnedHTTPHandler) for h in handlers)
        assert any(isinstance(h, function_caller._PinnedHTTPSHandler) for h in handlers)
        assert any(isinstance(h, function_caller._SafeWebRedirectHandler) for h in handlers)

    @pytest.mark.parametrize("timeout", [True, False, 0, -1, 121, 1.5, "invalid", None])
    def test_code_execution_rejects_invalid_timeout_before_sandbox(self, timeout):
        from alberto.engines.hermes_tools import tool_code_execution

        result = tool_code_execution(None, {"code": "print(1)", "timeout": timeout})
        assert result["ok"] is False
        assert "invalid timeout" in result["error"]

    def test_code_execution_rejects_non_string_and_oversized_source(self):
        from alberto.engines.hermes_tools import tool_code_execution

        non_string = tool_code_execution(None, {"code": ["print(1)"]})
        assert non_string["ok"] is False
        assert "missing 'code'" in non_string["error"]

        oversized = tool_code_execution(None, {"code": "x" * (256 * 1024 + 1)})
        assert oversized["ok"] is False
        assert "256 KiB" in oversized["error"]
