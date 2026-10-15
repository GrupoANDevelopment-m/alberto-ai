"""Regression tests for NemoClaw path containment and secret redaction."""
from pathlib import Path

import pytest

from alberto.runtime.nemoclaw_real import (
    PathViolation,
    redact_secrets,
    safe_resolve_path,
)


def test_relative_memory_path_must_remain_inside_sandbox(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    resolved = safe_resolve_path("memory/notes.txt", sandbox)

    assert resolved == (sandbox / "memory" / "notes.txt").resolve()
    assert resolved.is_relative_to(sandbox.resolve())


@pytest.mark.parametrize(
    "path",
    [
        "memory/../../outside.txt",
        "memory/../../../etc/passwd",
        "IDENTITY.md/../../outside.txt",
    ],
)
def test_traversal_in_workspace_prefixed_paths_is_rejected(tmp_path, path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    with pytest.raises(PathViolation, match="path escapes sandbox"):
        safe_resolve_path(path, sandbox)


def test_relative_symlink_cannot_escape_sandbox(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    memory = sandbox / "memory"
    memory.mkdir()
    link = memory / "linked.txt"

    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(PathViolation, match="path escapes sandbox"):
        safe_resolve_path("memory/linked.txt", sandbox)


def test_redaction_preserves_distinct_masks_for_distinct_secrets():
    first = "sk-abcdefghijklmnopqrstuvwx"
    second = "ghp_" + ("A" * 40)
    source = f"provider={first}; github={second}"

    redacted, findings = redact_secrets(source)

    assert first not in redacted
    assert second not in redacted
    assert first[:8] + "***" + first[-4:] in redacted
    assert second[:8] + "***" + second[-4:] in redacted
    assert len(findings) == 2
    assert {finding["pattern"] for finding in findings} == {
        "OpenAI API key",
        "GitHub token",
    }


def test_file_read_requires_sandbox_and_allows_in_sandbox_file(tmp_path):
    from types import SimpleNamespace
    from alberto.runtime.function_caller import tool_file_read

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    target = sandbox / "notes.txt"
    target.write_text("safe content", encoding="utf-8")
    alberto = SimpleNamespace(sandbox=SimpleNamespace(home=lambda: str(sandbox)))

    output, is_error = tool_file_read(alberto, {"path": "notes.txt"})

    assert is_error is False
    assert output == "safe content"


def test_file_read_rejects_relative_path_escape(tmp_path):
    from types import SimpleNamespace
    from alberto.runtime.function_caller import tool_file_read

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("must not be read", encoding="utf-8")
    alberto = SimpleNamespace(sandbox=SimpleNamespace(home=lambda: str(sandbox)))

    output, is_error = tool_file_read(alberto, {"path": "../outside.txt"})

    assert is_error is True
    assert "BLOCKED by NemoClaw" in output
    assert "must not be read" not in output


def test_file_read_fails_closed_without_configured_sandbox(tmp_path):
    from types import SimpleNamespace
    from alberto.runtime.function_caller import tool_file_read

    target = tmp_path / "readme.txt"
    target.write_text("content", encoding="utf-8")

    output, is_error = tool_file_read(SimpleNamespace(), {"path": str(target)})

    assert is_error is True
    assert "configured sandbox is required" in output
