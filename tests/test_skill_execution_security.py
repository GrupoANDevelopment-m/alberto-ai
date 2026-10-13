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
