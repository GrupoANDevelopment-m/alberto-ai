"""Behavioral contracts for Alberto coordination, context handoff, and learning."""
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_crewai_sequential_tasks_receive_previous_task_context(tmp_path, monkeypatch):
    from alberto.runtime import crewai_runtime as runtime

    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """
personas:
  - name: analyst
    role: Analyst
    system_prompt: Analyze facts.
  - name: reviewer
    role: Reviewer
    system_prompt: Review prior analysis.
workflow:
  - persona: analyst
    task: Analyze the request
    output_to: analysis
  - persona: reviewer
    task: Review the analysis
    output_to: review
""",
        encoding="utf-8",
    )

    created_tasks = []

    class FakeTask:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_tasks.append(self)

    class FakeCrew:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def kickoff(self):
            return "final result"

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeLLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeProcess:
        sequential = "sequential"

    monkeypatch.setattr(runtime, "_try_load_crewai", lambda: True)
    monkeypatch.setattr(runtime, "_Agent", FakeAgent)
    monkeypatch.setattr(runtime, "_Task", FakeTask)
    monkeypatch.setattr(runtime, "_Crew", FakeCrew)
    monkeypatch.setattr(runtime, "_Process", FakeProcess)
    monkeypatch.setattr(runtime, "_LLM", FakeLLM)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-only-placeholder")

    result = runtime.run_crew_squad(
        squad_name="contract-test",
        workflow_yaml_path=str(workflow),
        personas_dir=str(tmp_path),
        llm_model="test-model",
        user_prompt="preserve the user context",
    )

    assert result["ok"] is True
    assert result["outputs"]["final"] == "final result"
    assert len(created_tasks) == 2
    assert "preserve the user context" in created_tasks[0].kwargs["description"]
    assert "context" not in created_tasks[0].kwargs
    assert created_tasks[1].kwargs["context"] == [created_tasks[0]]
    assert "preceding workflow tasks" in created_tasks[1].kwargs["description"]


def test_skill_catalog_refresh_discovers_new_skills_and_preserves_stats(tmp_path, monkeypatch):
    from alberto.runtime import meta_controller

    discovered = [
        {
            "name": "existing-skill",
            "description": "old description",
            "category": "test",
            "tags": ["one"],
            "path": "skills/existing-skill/SKILL.md",
            "version": "0.1.0",
        }
    ]
    monkeypatch.setattr(
        "alberto.upstream_bridge.list_upstream_skills",
        lambda: list(discovered),
    )
    agent = SimpleNamespace(sandbox=SimpleNamespace(home=lambda: tmp_path))
    manager = meta_controller.SkillManager(agent)
    manager.record_outcome("existing-skill", success=True, duration=1.25)

    discovered.append(
        {
            "name": "learned-skill",
            "description": "created during runtime",
            "category": "user",
            "tags": ["learned"],
            "path": "skills/user/learned-skill/SKILL.md",
            "version": "0.1.0",
        }
    )
    assert manager.refresh() == 2
    manager._save_stats()

    assert "learned-skill" in manager.index
    assert manager.index["existing-skill"]["stats"]["success"] == 1
    assert manager.index["existing-skill"]["stats"]["total_time"] == pytest.approx(1.25)


def test_learning_profile_persists_observations_and_returns_adaptation_hints(tmp_path):
    from alberto.runtime.learner import Learner

    class Memory:
        pass

    learner = Learner(
        SimpleNamespace(home=lambda: tmp_path),
        Memory(),
    )
    learner.observe_interaction(
        "Por favor, explique detalhadamente esta arquitetura",
        "Aqui está uma explicação detalhada.",
    )

    # Reload from disk to prove this is persistent state, not in-memory only.
    reloaded = Learner(SimpleNamespace(home=lambda: tmp_path), Memory())
    assert reloaded.profile["interactions"] == 1
    assert reloaded.get_adaptation_hints()["style"] == "Provide thorough explanations with examples"
    assert (tmp_path / ".mimo" / "user_profile.json").is_file()



def test_alberto_can_delegate_squad_execution_to_crewai(monkeypatch):
    import os
    from alberto.agent import Alberto
    from alberto.model_router import ModelSpec

    calls = []
    spec = ModelSpec(
        provider="openrouter",
        model_id="openrouter/test-model",
        base_url="https://openrouter.ai/api",
        credential_env="OPENROUTER_API_KEY",
    )
    agent = Alberto.__new__(Alberto)
    agent.catalog = SimpleNamespace(get=lambda _name: object())
    agent.router = SimpleNamespace(
        config=SimpleNamespace(resolve=lambda task: spec if task == "chat" else None)
    )
    monkeypatch.setenv("ALBERTO_SQUAD_ENGINE", "crewai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-placeholder")

    def fake_run_crew_squad(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "outputs": {"final": "crew result"}}

    from alberto.runtime import crewai_runtime
    monkeypatch.setattr(crewai_runtime, "run_crew_squad", fake_run_crew_squad)

    result = agent.run_squad("engineering", "preserve this exact request")

    assert result["ok"] is True
    assert result["engine"] == "crewai"
    assert calls[0]["squad_name"] == "engineering"
    assert calls[0]["llm_model"] == "openrouter/test-model"
    assert calls[0]["llm_base_url"] == "https://openrouter.ai/api"
    assert calls[0]["llm_api_key"] == "test-only-placeholder"
    assert calls[0]["user_prompt"] == "preserve this exact request"
    assert Path(calls[0]["workflow_yaml_path"]).name == "engineering.yaml"


def test_skill_evolution_changes_executable_block_and_bumps_quoted_version(tmp_path, monkeypatch):
    from alberto.runtime import skill_engine
    from alberto.runtime.learner import Learner

    learner = Learner(SimpleNamespace(home=lambda: tmp_path / "home"), mimo=None)
    learner.user_skills_dir = tmp_path / "skills" / "user"
    path = learner.create_skill(
        "runtime-skill",
        description="A test skill",
        content="Run this command:\n\n```bash\necho old\n```",
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda _name: path)

    evolved = learner.evolve_skill(
        "runtime-skill",
        improvements="The command now emits the revised marker.",
        new_code_blocks=[{"lang": "bash", "code": "echo revised"}],
    )
    text = evolved.read_text(encoding="utf-8")
    assert "```bash\necho revised\n```" in text
    assert "echo old" not in text
    assert 'version: "0.1.1"' in text


def test_skill_evolution_rejects_prose_only_changes(tmp_path, monkeypatch):
    from alberto.runtime import skill_engine
    from alberto.runtime.learner import Learner

    learner = Learner(SimpleNamespace(home=lambda: tmp_path / "home"), mimo=None)
    learner.user_skills_dir = tmp_path / "skills" / "user"
    path = learner.create_skill(
        "runtime-skill",
        description="A test skill",
        content="Run this command:\n\n```bash\necho stable\n```",
    )
    monkeypatch.setattr(skill_engine, "find_skill", lambda _name: path)
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="concrete executable code blocks"):
        learner.evolve_skill("runtime-skill", improvements="This is only prose.")

    assert path.read_text(encoding="utf-8") == before


def test_alberto_preserves_recent_context_when_delegating_to_native_squad():
    from alberto.agent import Alberto

    step = SimpleNamespace(persona="analyst", task="Answer the current request", output_to="answer")
    squad = SimpleNamespace(workflow=[step], personas={})
    calls = []
    agent = Alberto.__new__(Alberto)
    agent.catalog = SimpleNamespace(get=lambda _name: squad)
    agent.personas = SimpleNamespace(get=lambda _name: None)
    agent.router = SimpleNamespace(
        invoke=lambda task, messages, **kwargs: (
            calls.append((task, messages, kwargs))
            or {"choices": [{"message": {"content": "context preserved"}}]}
        )
    )

    result = agent.run_squad(
        "engineering",
        "What did we decide?",
        context_messages=[
            {"role": "system", "content": "Respect the established project constraints."},
            {"role": "user", "content": "Use Alberto as the central coordinator."},
            {"role": "assistant", "content": "Confirmed; Hermes and MiMo are components."},
            {"role": "user", "content": "What did we decide?"},
        ],
    )

    assert result["outputs"]["answer"] == "context preserved"
    submitted = calls[0][1][1]["content"]
    assert "Use Alberto as the central coordinator." in submitted
    assert "Hermes and MiMo are components." in submitted
    assert "CURRENT USER REQUEST" in submitted
    assert "What did we decide?" in submitted
