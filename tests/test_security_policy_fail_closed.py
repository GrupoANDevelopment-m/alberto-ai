"""Security-policy availability must not silently disable write protections."""
import builtins
from pathlib import Path

from alberto.runtime import function_caller


def block_nemoclaw_import(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "nemoclaw_real" and level == 1:
            raise ImportError("simulated broken security module")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_file_write_fails_closed_if_security_policy_cannot_load(tmp_path, monkeypatch):
    target = tmp_path / "must-not-exist.txt"
    block_nemoclaw_import(monkeypatch)

    output, is_error = function_caller.tool_file_write(
        None, {"path": str(target), "content": "unsafe fallback"}
    )

    assert is_error is True
    assert "security policy unavailable" in output
    assert not target.exists()


def test_mimo_write_fails_closed_if_security_policy_cannot_load(tmp_path, monkeypatch):
    target = tmp_path / "must-not-exist.txt"
    block_nemoclaw_import(monkeypatch)

    output, is_error = function_caller.tool_write(
        None, {"path": str(target), "content": "unsafe fallback"}
    )

    assert is_error is True
    assert "security policy unavailable" in output
    assert not target.exists()


def test_edit_fails_closed_if_secret_policy_cannot_load(tmp_path, monkeypatch):
    target = tmp_path / "existing.txt"
    target.write_text("original", encoding="utf-8")
    block_nemoclaw_import(monkeypatch)

    output, is_error = function_caller.tool_edit(
        None, {"path": str(target), "old_text": "original", "new_text": "changed"}
    )

    assert is_error is True
    assert "security policy unavailable" in output
    assert target.read_text(encoding="utf-8") == "original"
