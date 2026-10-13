"""Regression tests for multiedit security controls."""
from pathlib import Path

from alberto.runtime.function_caller import tool_apply_patch, tool_edit, tool_multiedit


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


def test_apply_patch_blocks_protected_target(tmp_path, monkeypatch):
    from alberto.runtime import upstream_bridge

    monkeypatch.setattr(upstream_bridge, "_get", lambda name: None)
    alberto = FakeAlberto(tmp_path)
    output, is_error = tool_apply_patch(
        alberto,
        {"path": "/etc/passwd", "patch": "@@ -1,1 +1,1 @@\n-root\n+changed"},
    )

    assert is_error is True
    assert "BLOCKED" in output


def test_apply_patch_still_writes_inside_sandbox(tmp_path, monkeypatch):
    from alberto.runtime import upstream_bridge

    monkeypatch.setattr(upstream_bridge, "_get", lambda name: None)
    alberto = FakeAlberto(tmp_path)
    target = tmp_path / "notes.txt"
    target.write_text("before", encoding="utf-8")

    output, is_error = tool_apply_patch(
        alberto,
        {"path": str(target), "patch": "@@ -1,1 +1,1 @@\n-before\n+after"},
    )

    assert is_error is False
    assert "patched" in output
    assert target.read_text(encoding="utf-8") == "after"


def test_edit_blocks_protected_target(tmp_path):
    alberto = FakeAlberto(tmp_path)

    output, is_error = tool_edit(
        alberto, {"path": "/etc/passwd", "old_text": "root", "new_text": "other"}
    )

    assert is_error is True
    assert "BLOCKED" in output or "blocked" in output.lower()


def test_edit_still_updates_file_inside_sandbox(tmp_path):
    alberto = FakeAlberto(tmp_path)
    target = tmp_path / "notes.txt"
    target.write_text("before", encoding="utf-8")

    output, is_error = tool_edit(
        alberto, {"path": str(target), "old_text": "before", "new_text": "after"}
    )

    assert is_error is False
    assert target.read_text(encoding="utf-8") == "after"


def test_edit_preserves_secret_rejection_contract(tmp_path):
    alberto = FakeAlberto(tmp_path)
    target = tmp_path / "notes.txt"
    target.write_text("before", encoding="utf-8")
    candidate_secret = "sk-abcdefghijklmnopqrstuvwxyz123456"

    output, is_error = tool_edit(
        alberto,
        {"path": str(target), "old_text": "before", "new_text": candidate_secret},
    )

    assert is_error is True
    assert "contains secrets" in output
    assert target.read_text(encoding="utf-8") == "before"
