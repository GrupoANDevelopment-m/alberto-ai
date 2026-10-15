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
