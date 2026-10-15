"""Regression tests for Hermes execution tools using the configured sandbox."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

from alberto.engines import hermes_tools


class RecordingSandbox:
    def __init__(self, home):
        self._home = Path(home)
        self.writes = []
        self.calls = []

    def home(self):
        return self._home

    def write(self, path, content):
        self.writes.append((Path(path), content))

    def run(self, command, *, timeout=60, cwd=None):
        self.calls.append((command, timeout, cwd))
        if command and command[0] == "rm":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "sandbox output\n", "")


def test_terminal_tool_routes_command_through_sandbox(tmp_path, monkeypatch):
    sandbox = RecordingSandbox(tmp_path)
    monkeypatch.setattr(
        hermes_tools,
        "_try_import",
        lambda name: (_ for _ in ()).throw(AssertionError("must not bypass configured sandbox")),
    )

    result = hermes_tools.tool_terminal(
        SimpleNamespace(sandbox=sandbox),
        {"command": "printf safe", "timeout": 12},
    )

    assert result["ok"] is True
    assert result["stdout"] == "sandbox output\n"
    assert sandbox.calls == [(["bash", "-lc", "printf safe"], 12, tmp_path)]


def test_code_execution_writes_and_runs_python_inside_sandbox(tmp_path, monkeypatch):
    sandbox = RecordingSandbox(tmp_path)
    monkeypatch.setattr(
        hermes_tools,
        "_try_import",
        lambda name: (_ for _ in ()).throw(AssertionError("must not bypass configured sandbox")),
    )
    monkeypatch.setattr(hermes_tools.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("direct subprocess forbidden")))

    result = hermes_tools.tool_code_execution(
        SimpleNamespace(sandbox=sandbox),
        {"code": "print('hello')", "language": "python", "timeout": 15},
    )

    assert result["ok"] is True
    assert sandbox.writes and sandbox.writes[0][1] == "print('hello')"
    command, timeout, cwd = sandbox.calls[0]
    assert command[0] != "rm"
    assert command[1].endswith(".py")
    assert timeout == 15
    assert cwd == tmp_path
    assert sandbox.calls[-1][0][:2] == ["rm", "-f"]


def test_code_execution_refuses_without_sandbox():
    result = hermes_tools.tool_code_execution(SimpleNamespace(), {"code": "print('hello')"})

    assert result["ok"] is False
    assert "sandbox is required" in result["error"]


def test_terminal_reports_nonzero_exit_as_failure(tmp_path):
    class FailedSandbox(RecordingSandbox):
        def run(self, command, *, timeout=60, cwd=None):
            self.calls.append((command, timeout, cwd))
            return subprocess.CompletedProcess(command, 2, "", "failed")

    sandbox = FailedSandbox(tmp_path)
    result = hermes_tools.tool_terminal(
        SimpleNamespace(sandbox=sandbox),
        {"command": "false"},
    )

    assert result["ok"] is False
    assert result["returncode"] == 2


def test_browser_rejects_private_target_before_importing_browser_tool(monkeypatch):
    monkeypatch.setattr(
        hermes_tools,
        "_try_import",
        lambda name: (_ for _ in ()).throw(AssertionError("unsafe target must be rejected first")),
    )

    result = hermes_tools.tool_browser(
        SimpleNamespace(),
        {"url": "http://127.0.0.1/admin"},
    )

    assert result["ok"] is False
    assert "unsafe browser URL" in result["error"]


def test_file_tool_reads_and_writes_only_inside_sandbox(tmp_path, monkeypatch):
    sandbox = __import__("alberto.sandbox.base", fromlist=["LocalSandbox"]).LocalSandbox(
        base_dir=tmp_path / "sandbox",
    )
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    write_result = hermes_tools.tool_file(
        SimpleNamespace(sandbox=sandbox),
        {"action": "write", "path": "workspace/note.txt", "content": "hello"},
    )
    read_result = hermes_tools.tool_file(
        SimpleNamespace(sandbox=sandbox),
        {"action": "read", "path": "workspace/note.txt"},
    )
    blocked = hermes_tools.tool_file(
        SimpleNamespace(sandbox=sandbox),
        {"action": "read", "path": str(outside)},
    )

    assert write_result["ok"] is True
    assert read_result == {"ok": True, "content": "hello"}
    assert blocked["ok"] is False
    assert "escapes sandbox" in blocked["error"]


def test_patch_apply_refuses_workspace_outside_sandbox(tmp_path):
    sandbox = RecordingSandbox(tmp_path / "sandbox")
    (tmp_path / "sandbox").mkdir()
    outside = tmp_path / "repo"
    outside.mkdir()

    result = hermes_tools._patch_apply(
        SimpleNamespace(sandbox=sandbox),
        {"patch": "diff --git a/a b/a", "workspace": str(outside)},
    )

    assert result["ok"] is False
    assert "escapes sandbox" in result["error"]
    assert sandbox.calls == []


def test_patch_apply_requires_configured_sandbox():
    result = hermes_tools._patch_apply(SimpleNamespace(), {"patch": "diff --git a/a b/a"})

    assert result["ok"] is False
    assert "sandbox is required" in result["error"]


def test_patch_apply_changes_file_inside_sandbox_workspace(tmp_path):
    from alberto.sandbox.base import LocalSandbox

    sandbox = LocalSandbox(base_dir=tmp_path / "sandbox")
    sandbox.write(Path("hello.txt"), "old\n")
    patch = (
        "diff --git a/hello.txt b/hello.txt\n"
        "--- a/hello.txt\n"
        "+++ b/hello.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    result = hermes_tools._patch_apply(
        SimpleNamespace(sandbox=sandbox),
        {"patch": patch, "workspace": "."},
    )

    assert result["ok"] is True
    assert sandbox.read(Path("hello.txt")) == "new\n"


def test_mimo_worktree_uses_sandbox_and_rejects_paths_outside_home(tmp_path, monkeypatch):
    from alberto.engines.hermes_tools import _mimo_worktree

    home = tmp_path / "sandbox"
    repo = home / "repo"
    (repo / ".git").mkdir(parents=True)
    sandbox = RecordingSandbox(home)
    result = _mimo_worktree(
        SimpleNamespace(sandbox=sandbox),
        {"path": "worktrees/session-1", "cwd": "repo", "branch": "session-1"},
    )
    assert result["ok"] is True
    assert len(sandbox.calls) == 3
    assert sandbox.calls[0][0] == ["git", "check-ref-format", "--branch", "session-1"]
    assert sandbox.calls[1][0] == ["mkdir", "-p", "worktrees"]
    assert sandbox.calls[2][0] == ["git", "worktree", "add", "-b", "session-1", "worktrees/session-1"]
    assert all(call[2] == repo for call in sandbox.calls)

    outside = tmp_path / "outside"
    blocked_path = _mimo_worktree(
        SimpleNamespace(sandbox=sandbox),
        {"path": str(outside), "cwd": "repo", "branch": "session-2"},
    )
    blocked_cwd = _mimo_worktree(
        SimpleNamespace(sandbox=sandbox),
        {"path": "worktrees/session-2", "cwd": str(outside), "branch": "session-2"},
    )
    assert blocked_path["ok"] is False
    assert blocked_cwd["ok"] is False
    assert len(sandbox.calls) == 3


def test_mimo_worktree_rejects_invalid_branch_and_requires_sandbox(tmp_path):
    from alberto.engines.hermes_tools import _mimo_worktree

    home = tmp_path / "sandbox"
    repo = home / "repo"
    (repo / ".git").mkdir(parents=True)
    sandbox = RecordingSandbox(home)
    invalid = _mimo_worktree(
        SimpleNamespace(sandbox=sandbox),
        {"path": "worktrees/session", "cwd": "repo", "branch": "../escape"},
    )
    missing = _mimo_worktree(SimpleNamespace(), {"path": "worktrees/session"})
    assert invalid["ok"] is False
    assert "branch" in invalid["error"]
    assert sandbox.calls == []
    assert missing["ok"] is False
    assert "sandbox is required" in missing["error"]


def test_tts_rejects_output_outside_sandbox_before_provider_dispatch(tmp_path, monkeypatch):
    from alberto.engines.hermes_tools import tool_voice_tts

    home = tmp_path / "sandbox"
    home.mkdir()
    outside = tmp_path / "outside.mp3"
    monkeypatch.setattr(
        hermes_tools, "_try_import",
        lambda _name: (_ for _ in ()).throw(AssertionError("provider must not be called for unsafe output")),
    )
    result = tool_voice_tts(
        SimpleNamespace(sandbox=RecordingSandbox(home)),
        {"text": "hello", "output_path": str(outside)},
    )
    assert result["ok"] is False
    assert "escapes sandbox home" in result["error"]
    assert not outside.exists()


def test_tts_writes_and_verifies_regular_file_inside_sandbox(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from alberto.engines.hermes_tools import tool_voice_tts

    home = tmp_path / "sandbox"
    home.mkdir()
    sandbox = RecordingSandbox(home)
    calls = []

    def synthesize(*, text, provider, voice, output):
        calls.append((text, provider, voice, Path(output)))
        Path(output).write_bytes(b"real-audio-bytes")
        return {"duration": 1.0}

    monkeypatch.setattr(hermes_tools, "_try_import", lambda _name: SimpleNamespace(synthesize=synthesize))
    result = tool_voice_tts(
        SimpleNamespace(sandbox=sandbox),
        {"text": "hello", "provider": "edge", "output_path": "audio/test.mp3"},
    )
    expected = home / "audio" / "test.mp3"
    assert result["ok"] is True
    assert Path(result["output"]) == expected
    assert expected.read_bytes() == b"real-audio-bytes"
    assert calls == [("hello", "edge", "", expected)]


def test_tts_rejects_symlinked_output_parent_escaping_sandbox(tmp_path, monkeypatch):
    from alberto.engines.hermes_tools import tool_voice_tts

    home = tmp_path / "sandbox"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / "audio").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        hermes_tools, "_try_import",
        lambda _name: (_ for _ in ()).throw(AssertionError("provider must not be called for symlink escape")),
    )
    result = tool_voice_tts(
        SimpleNamespace(sandbox=RecordingSandbox(home)),
        {"text": "hello", "output_path": "audio/escape.mp3"},
    )
    assert result["ok"] is False
    assert "escapes sandbox home" in result["error"]
    assert not (outside / "escape.mp3").exists()
