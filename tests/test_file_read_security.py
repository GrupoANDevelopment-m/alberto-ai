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



@pytest.mark.parametrize(
    ("start_line", "max_lines"),
    [(-1, 10), (100001, 10), (0, 0), (0, 2001), (True, 10), (0, False), ("bad", 10)],
)
def test_mimo_read_rejects_invalid_line_ranges(tmp_path, start_line, max_lines):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("one\ntwo\n", encoding="utf-8")
    output, is_error = tool_read(None, {
        "path": str(file_path), "start_line": start_line, "max_lines": max_lines
    })
    assert is_error is True
    assert "invalid line range" in output


def test_mimo_read_streams_only_requested_window_and_caps_output(tmp_path):
    file_path = tmp_path / "large.txt"
    file_path.write_text("first\n" + ("x" * 250_000) + "\nlast\n", encoding="utf-8")

    output, is_error = tool_read(None, {
        "path": str(file_path), "start_line": 1, "max_lines": 1
    })

    assert is_error is False
    assert "2|" in output
    assert len(output) < 100_200
    assert output.endswith("[truncated: file read output limit reached]")



def test_mimo_read_rejects_files_over_size_limit_before_loading(tmp_path):
    file_path = tmp_path / "oversized.txt"
    with file_path.open("wb") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)

    output, is_error = tool_read(None, {"path": str(file_path)})
    assert is_error is True
    assert "10 MiB limit" in output
