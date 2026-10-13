"""Regression tests for sensitive-file read protection."""
from pathlib import Path

import pytest

from alberto.runtime.function_caller import tool_file_read


def test_file_read_blocks_protected_system_file():
    output, is_error = tool_file_read(None, {"path": "/etc/passwd"})
    assert is_error is True
    assert "BLOCKED" in output


def test_file_read_blocks_symlink_to_protected_file(tmp_path):
    protected = Path("/etc/passwd")
    if not protected.exists():
        pytest.skip("requires a Unix-like test runner with /etc/passwd")
    link = tmp_path / "harmless.txt"
    try:
        link.symlink_to(protected)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    output, is_error = tool_file_read(None, {"path": str(link)})
    assert is_error is True
    assert "BLOCKED" in output


def test_file_read_still_allows_regular_workspace_file(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("normal content", encoding="utf-8")

    output, is_error = tool_file_read(None, {"path": str(file_path)})

    assert is_error is False
    assert output == "normal content"
