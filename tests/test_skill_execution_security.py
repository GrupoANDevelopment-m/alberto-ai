"""Regression tests for skill argument handling and sandbox execution."""
from pathlib import Path
from types import SimpleNamespace

from alberto.runtime import function_caller, skill_engine
from alberto.sandbox.base import LocalSandbox


def write_skill(tmp_path, name, block):
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n{block}\n",
        encoding="utf-8",
    )
    return path


def code_block(language, code):
    fence = chr(96) * 3
    return f"{fence}{language}\n{code}\n{fence}"


def test_shell_skill_argument_cannot_inject_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", "1")
    marker = tmp_path / "owned"
    payload = f'"; touch {marker}; echo "'
    skill_path = write_skill(
        tmp_path,
        "shell-argument-test",
        code_block("bash", "printf '%s' {{args[0]}}"),
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    sandbox = LocalSandbox(base_dir=tmp_path / "sandbox")

    result = skill_engine.run_skill("shell-argument-test", [payload], sandbox=sandbox)

    assert result["ok"] is True
    assert result["stdout"] == payload
    assert not marker.exists()


def test_python_skill_argument_is_a_string_literal(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", "1")
    marker = tmp_path / "python-owned"
    payload = f'"); __import__("os").system("touch {marker}"); print("'
    skill_path = write_skill(
        tmp_path,
        "python-argument-test",
        code_block("python", "print({{args[0]}})"),
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    sandbox = LocalSandbox(base_dir=tmp_path / "sandbox")

    result = skill_engine.run_skill("python-argument-test", [payload], sandbox=sandbox)

    assert result["ok"] is True
    assert result["stdout"] == payload + "\n"
    assert not marker.exists()


def test_skill_without_executable_block_is_not_run(tmp_path, monkeypatch):
    skill_path = write_skill(
        tmp_path,
        "documentation-only",
        code_block("json", '{"action": "not executable"}'),
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    sandbox = LocalSandbox(base_dir=tmp_path / "sandbox")

    result = skill_engine.run_skill("documentation-only", [], sandbox=sandbox)

    assert result["ok"] is False
    assert "no executable code block" in result["error"]


def test_skill_execution_requires_explicit_sandbox(tmp_path, monkeypatch):
    skill_path = write_skill(
        tmp_path,
        "sandbox-required",
        code_block("bash", "echo safe"),
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)

    result = skill_engine.run_skill("sandbox-required", [])

    assert result["ok"] is False
    assert "sandbox is required" in result["error"]


def test_tool_skill_passes_parsed_args_and_propagates_failure(monkeypatch):
    calls = []
    sandbox = object()

    def fake_run_skill(name, args, *, sandbox=None, timeout=60):
        calls.append((name, args, sandbox, timeout))
        return {"ok": False, "error": "expected failure"}

    monkeypatch.setattr(skill_engine, "run_skill", fake_run_skill)
    monkeypatch.setattr(skill_engine, "list_skills", lambda: [{"name": "sample-skill"}])
    alberto = SimpleNamespace(sandbox=sandbox)

    output, is_error = function_caller.tool_skill(
        alberto, {"name": "sample-skill", "input": '"hello world" --mode safe'}
    )

    assert is_error is True
    assert "expected failure" in output
    assert calls == [("sample-skill", ["hello world", "--mode", "safe"], sandbox, 60)]


def test_tool_skill_list_formats_dictionary_records(monkeypatch):
    monkeypatch.setattr(skill_engine, "list_skills", lambda: [{"name": "alpha"}, {"name": "beta"}])

    output, is_error = function_caller.tool_skill(None, {"action": "list"})

    assert is_error is False
    assert output == "alpha\nbeta"


def test_tool_skill_show_uses_content_helper(monkeypatch):
    monkeypatch.setattr(skill_engine, "get_skill_content", lambda name: "skill body")

    output, is_error = function_caller.tool_skill(None, {"action": "show", "name": "sample"})

    assert is_error is False
    assert output == "skill body"


def test_python_args_placeholder_expands_multiple_literals(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", "1")
    skill_path = write_skill(
        tmp_path,
        "python-multiple-args",
        code_block("python", "print({{args}})"),
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    sandbox = LocalSandbox(base_dir=tmp_path / "sandbox")

    result = skill_engine.run_skill("python-multiple-args", ["alpha", "beta"], sandbox=sandbox)

    assert result["ok"] is True
    assert result["stdout"] == "alpha beta\n"


def test_skill_cli_run_all_uses_configured_sandbox_and_returns_failure(tmp_path, monkeypatch):
    import subprocess
    from alberto.runtime import skill_engine

    skill_path = write_skill(
        tmp_path,
        "failing-skill",
        code_block("bash", "exit 7"),
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    monkeypatch.setenv("ALBERTO_SANDBOX_KIND", "nemoclaw")

    class FakeSandbox:
        isolation_level = "docker-container"
        _mode = "docker"

        def __init__(self):
            self.calls = []

        def home(self):
            return tmp_path

        def run(self, command, *, timeout=60, cwd=None):
            self.calls.append((command, timeout, cwd))
            return subprocess.CompletedProcess(command, 7, "", "expected failure")

    fake = FakeSandbox()
    kinds = []
    monkeypatch.setattr(
        "alberto.sandbox.base.make_sandbox",
        lambda kind: kinds.append(kind) or fake,
    )

    result = skill_engine.main(["run-all", "failing-skill"])

    assert result == 1
    assert kinds == ["nemoclaw"]
    assert fake.calls == [(["bash", "-c", "exit 7"], 60, str(tmp_path))]


def test_skill_cli_run_all_refuses_host_execution_without_opt_in(tmp_path, monkeypatch, capsys):
    skill_path = write_skill(
        tmp_path,
        "host-run-all-refused",
        code_block("bash", "echo must-not-run"),
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    monkeypatch.delenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", raising=False)
    monkeypatch.setenv("ALBERTO_SANDBOX_KIND", "local")

    class FakeHostSandbox:
        def __init__(self):
            self.calls = []

        def home(self):
            return tmp_path

        def run(self, command, *, timeout=60, cwd=None):
            self.calls.append(command)
            raise AssertionError("host command must not execute")

    fake = FakeHostSandbox()
    monkeypatch.setattr("alberto.sandbox.base.make_sandbox", lambda kind: fake)

    result = skill_engine.main(["run-all", "host-run-all-refused"])

    assert result == 1
    assert fake.calls == []
    assert "Docker isolation is required" in capsys.readouterr().err


def test_generated_user_skill_requires_explicit_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", "1")
    monkeypatch.delenv("ALBERTO_ALLOW_UNTRUSTED_SKILL_EXECUTION", raising=False)
    user_dir = tmp_path / "skills" / "user"
    skill_path = write_skill(
        user_dir,
        "generated-skill",
        code_block("bash", "echo should-not-run"),
    )
    monkeypatch.setattr(skill_engine, "USER_SKILLS_DIR", user_dir)
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    sandbox = LocalSandbox(base_dir=tmp_path / "sandbox")
    result = skill_engine.run_skill("generated-skill", [], sandbox=sandbox)
    assert result["ok"] is False
    assert "explicit operator approval is required" in result["error"]


def test_generated_user_skill_can_run_only_after_explicit_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", "1")
    monkeypatch.setenv("ALBERTO_ALLOW_UNTRUSTED_SKILL_EXECUTION", "1")
    user_dir = tmp_path / "skills" / "user"
    skill_path = write_skill(
        user_dir,
        "approved-generated-skill",
        code_block("bash", "echo approved"),
    )
    monkeypatch.setattr(skill_engine, "USER_SKILLS_DIR", user_dir)
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path)
    sandbox = LocalSandbox(base_dir=tmp_path / "sandbox")
    result = skill_engine.run_skill("approved-generated-skill", [], sandbox=sandbox)
    assert result["ok"] is True
    assert result["stdout"].strip() == "approved"


def test_generated_user_skill_symlink_escape_is_rejected(tmp_path, monkeypatch):
    user_dir = tmp_path / "skills" / "user"
    user_dir.mkdir(parents=True)
    outside = write_skill(tmp_path / "outside", "external-skill", code_block("bash", "echo outside"))
    link_dir = user_dir / "linked-skill"
    try:
        link_dir.symlink_to(outside.parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("symlinks are unavailable on this platform")
    monkeypatch.setattr(skill_engine, "USER_SKILLS_DIR", user_dir)
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: link_dir / "SKILL.md")
    result = skill_engine.run_skill("linked-skill", [])
    assert result["ok"] is False
    assert "symlinked skill paths" in result["error"] or "escapes the user skills directory" in result["error"]


def test_auto_invoke_does_not_route_to_missing_skill(monkeypatch):
    monkeypatch.setattr(
        skill_engine, "SKILL_KEYWORDS",
        [{"patterns": [r"\\bdeploy\\b"], "skill": "missing-deploy-skill", "description": "deployment"}],
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda _name: None)

    assert skill_engine.auto_invoke_skill("deploy this app") is None


def test_auto_invoke_routes_only_to_resolvable_skill(monkeypatch, tmp_path):
    skill_path = tmp_path / "deploy" / "SKILL.md"
    monkeypatch.setattr(
        skill_engine, "SKILL_KEYWORDS",
        [{"patterns": [r"\\bdeploy\\b"], "skill": "deploy-skill", "description": "deployment"}],
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda name: skill_path if name == "deploy-skill" else None)

    result = skill_engine.auto_invoke_skill("deploy this app")

    assert result is not None
    assert result["skill"] == "deploy-skill"
    assert result["description"] == "deployment"
