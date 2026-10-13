"""Regression tests for multiedit security controls."""
from pathlib import Path

from alberto.runtime.function_caller import tool_multiedit


class FakeSandbox:
    def __init__(self, home):
        self._home = Path(home)

    def home(self):
        return self._home


class FakeAlberto:
    def __init__(self, home):
        self.sandbox = FakeSandbox(home)


def test_multiedit_blocks_protected_system_file(tmp_path):
    alberto = FakeAlberto(tmp_path)

    output, is_error = tool_multiedit(
        alberto,
        {"path": "/etc/passwd", "edits": [{"old_text": "root", "new_text": "other"}]},
    )

    assert is_error is True
    assert "BLOCKED" in output


def test_multiedit_still_edits_file_inside_sandbox(tmp_path):
    alberto = FakeAlberto(tmp_path)
    target = tmp_path / "notes.txt"
    target.write_text("before", encoding="utf-8")

    output, is_error = tool_multiedit(
        alberto,
        {"path": str(target), "edits": [{"old_text": "before", "new_text": "after"}]},
    )

    assert is_error is False
    assert "1/1" in output
    assert target.read_text(encoding="utf-8") == "after"
