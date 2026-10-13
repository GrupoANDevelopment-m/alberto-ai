"""Regression tests for sensitive-path protections on both read tools."""
from pathlib import Path

import pytest

from alberto.runtime.function_caller import tool_file_read, tool_read


READ_TOOLS = [tool_file_read, tool_read]


@pytest.mark.parametrize("read_tool", READ_TOOLS)
def test_read_tool_blocks_protected_system_file(read_tool):
    output, is_error = read_tool(None, {"path": "/etc/passwd"})
    assert is_error is True
    assert "BLOCKED" in output


@pytest.mark.parametrize("read_tool", READ_TOOLS)
def test_read_tool_blocks_symlink_to_protected_file(read_tool, tmp_path):
    protected = Path("/etc/passwd")
    if not protected.exists():
        pytest.skip("requires a Unix-like test runner with /etc/passwd")
    link = tmp_path / "harmless.txt"
    try:
        link.symlink_to(protected)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    output, is_error = read_tool(None, {"path": str(link)})
    assert is_error is True
    assert "BLOCKED" in output


@pytest.mark.parametrize("read_tool", READ_TOOLS)
def test_read_tool_still_allows_regular_workspace_file(read_tool, tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("normal content", encoding="utf-8")

    output, is_error = read_tool(None, {"path": str(file_path)})

    assert is_error is False
    assert "normal content" in output
