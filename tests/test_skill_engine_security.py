"""Regression tests for fail-closed skill execution policy."""
from pathlib import Path
from types import SimpleNamespace
import subprocess

from alberto.runtime import skill_engine


def _skill_file(tmp_path: Path) -> Path:
    skill = tmp_path / "SKILL.md"
    skill.write_text("```bash\necho isolated\n```\n", encoding="utf-8")
    return skill


def test_run_skill_refuses_host_execution_without_explicit_opt_in(tmp_path, monkeypatch):
    skill_path = _skill_file(tmp_path)
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    monkeypatch.delenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", raising=False)
    calls = []
    sandbox = SimpleNamespace(
        isolation_level="host-process",
        home=lambda: tmp_path,
        run=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = skill_engine.run_skill("untrusted-skill", [], sandbox=sandbox)

    assert result["ok"] is False
    assert "Docker isolation is required" in result["error"]
    assert calls == []


def test_run_skill_allows_execution_through_docker_sandbox(tmp_path, monkeypatch):
    skill_path = _skill_file(tmp_path)
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    monkeypatch.delenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", raising=False)
    calls = []

    def docker_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="isolated\n", stderr="")

    sandbox = SimpleNamespace(
        isolation_level="docker-container",
        _mode="docker",
        home=lambda: Path("/tmp"),
        run=docker_run,
    )

    result = skill_engine.run_skill("verified-skill", [], sandbox=sandbox, timeout=7)

    assert result["ok"] is True
    assert result["stdout"] == "isolated\n"
    assert calls[0][0] == ["bash", "-c", "echo isolated"]
    assert calls[0][1]["timeout"] == 7


def test_run_skill_host_execution_requires_explicit_development_opt_in(tmp_path, monkeypatch):
    skill_path = _skill_file(tmp_path)
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    monkeypatch.setenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", "1")
    calls = []

    def host_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="dev-only\n", stderr="")

    sandbox = SimpleNamespace(
        isolation_level="host-process",
        home=lambda: tmp_path,
        run=host_run,
    )

    result = skill_engine.run_skill("development-skill", [], sandbox=sandbox)

    assert result["ok"] is True
    assert result["stdout"] == "dev-only\n"
    assert calls
