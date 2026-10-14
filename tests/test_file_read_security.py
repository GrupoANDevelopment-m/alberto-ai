"""Regression tests for sensitive-path protections on both read tools."""
from pathlib import Path

import pytest

from alberto.runtime.function_caller import tool_file_read, tool_grep, tool_read


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


def test_grep_blocks_protected_search_root():
    output, is_error = tool_grep(None, {"pattern": "root", "path": "/etc/passwd"})
    assert is_error is True
    assert "BLOCKED" in output


def test_grep_skips_symlink_to_protected_file(tmp_path):
    protected = Path("/etc/passwd")
    if not protected.exists():
        pytest.skip("requires a Unix-like test runner with /etc/passwd")
    link = tmp_path / "harmless.txt"
    try:
        link.symlink_to(protected)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    output, is_error = tool_grep(None, {"pattern": "root:", "path": str(tmp_path)})
    assert is_error is False
    assert "no matches" in output
    assert "root:x:0:0" not in output



@pytest.mark.parametrize("max_lines", [0, -1, 2001, True, 1.5, "nope"])
def test_file_read_rejects_invalid_line_limits(tmp_path, max_lines):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("one\\ntwo\\n", encoding="utf-8")
    output, is_error = tool_file_read(None, {
        "path": str(file_path), "max_lines": max_lines
    })
    assert is_error is True
    assert "invalid max_lines" in output


def test_file_read_streams_and_caps_very_large_single_line(tmp_path):
    file_path = tmp_path / "large.txt"
    file_path.write_text("x" * 250_000, encoding="utf-8")

    output, is_error = tool_file_read(None, {"path": str(file_path), "max_lines": 1})

    assert is_error is False
    assert len(output) < 100_100
    assert output.endswith("[truncated: file read output limit reached]")
