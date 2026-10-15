"""Focused unit tests for core agent decision and formatting paths."""
from types import SimpleNamespace

import pytest

from alberto.agent import Alberto, resolve_sandbox_kind


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "local"),
        ({"ALBERTO_SANDBOX_KIND": "nemoclaw"}, "nemoclaw"),
        ({"ALBERTO_SANDBOX_KIND": "LOCAL"}, "local"),
        ({"ALBERTO_REQUIRE_DOCKER": "1"}, "nemoclaw"),
        ({"ALBERTO_REQUIRE_DOCKER": "yes"}, "nemoclaw"),
        ({"ALBERTO_REQUIRE_DOCKER": "false", "ALBERTO_SANDBOX_KIND": "custom"}, "custom"),
    ],
)
def test_resolve_sandbox_kind(env, expected):
    assert resolve_sandbox_kind(env) == expected


@pytest.mark.parametrize("value", ["local", "LOCAL", ""])
def test_resolve_sandbox_kind_fails_closed_on_docker_conflict(value):
    env = {"ALBERTO_REQUIRE_DOCKER": "true", "ALBERTO_SANDBOX_KIND": value}
    if value == "":
        assert resolve_sandbox_kind(env) == "nemoclaw"
    else:
        with pytest.raises(RuntimeError, match="Refusing to run"):
            resolve_sandbox_kind(env)


def test_format_squad_result_handles_empty_and_mixed_outputs():
    agent = Alberto.__new__(Alberto)
    text = agent._format_squad_result({
        "squad": "audit",
        "outputs": {
            "empty": None,
            "plain": "done",
            "structured": {"ok": True, "count": 2},
        },
    })
    assert "Squad `audit`" in text
    assert "(vazio)" in text
    assert "done" in text
    assert '"ok": true' in text


def test_format_max_mode_handles_missing_winner():
    agent = Alberto.__new__(Alberto)
    assert agent._format_max_mode({}) == "[max mode: no winner]"
    assert agent._format_max_mode({"winner": {"content": "best"}}) == "best"


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("deepseek-ai/deepseek-v4", True),
        ("openai/gpt-4.1", True),
        ("anthropic/claude-3", True),
        ("meta/llama-3.3-70b", True),
        ("unknown/custom-model", False),
    ],
)
def test_supports_function_calling_known_model_heuristic(model_id, expected):
    agent = Alberto.__new__(Alberto)
    agent.router = SimpleNamespace(config=SimpleNamespace(
        resolve=lambda task: SimpleNamespace(model_id=model_id)
    ))
    assert agent._supports_function_calling() is expected


def test_supports_function_calling_without_model_defaults_false():
    agent = Alberto.__new__(Alberto)
    agent.router = SimpleNamespace(config=SimpleNamespace(resolve=lambda task: None))
    assert agent._supports_function_calling() is False


def test_supports_function_calling_handles_router_failure():
    agent = Alberto.__new__(Alberto)
    agent.router = SimpleNamespace(config=SimpleNamespace(
        resolve=lambda task: (_ for _ in ()).throw(RuntimeError("router unavailable"))
    ))
    assert agent._supports_function_calling() is False


def test_run_squad_unknown_name_returns_error():
    agent = Alberto.__new__(Alberto)
    agent.catalog = SimpleNamespace(get=lambda name: None)
    assert agent.run_squad("missing", "task") == {"error": "unknown squad: missing"}


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (None, "[step analyst: empty response]"),
        ({}, "[step analyst: no choices in response]"),
        ({"choices": []}, "[step analyst: no choices in response]"),
        ({"choices": [{"message": {"content": "analysis complete"}}]}, "analysis complete"),
        ({"choices": [{"message": {}}]}, "[step analyst: no content in response]"),
        ("raw provider output", "raw provider output"),
    ],
)
def test_run_squad_normalizes_provider_response_shapes(response, expected):
    step = SimpleNamespace(persona="analyst", task="Analyze {prior}", output_to="analysis")
    squad = SimpleNamespace(
        workflow=[step],
        personas={},
    )
    agent = Alberto.__new__(Alberto)
    agent.catalog = SimpleNamespace(get=lambda name: squad)
    agent.personas = SimpleNamespace(get=lambda name: None)
    agent.router = SimpleNamespace(invoke=lambda *args, **kwargs: response)

    result = agent.run_squad("test-squad", "user task")
    assert result["squad"] == "test-squad"
    assert result["outputs"]["analysis"] == expected


def test_run_squad_catches_provider_exceptions_and_continues():
    steps = [
        SimpleNamespace(persona="first", task="first task", output_to="first"),
        SimpleNamespace(persona="second", task="use {first}", output_to="second"),
    ]
    squad = SimpleNamespace(workflow=steps, personas={})
    calls = {"count": 0}

    def invoke(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("provider timed out")
        return {"choices": [{"message": {"content": "recovered"}}]}

    agent = Alberto.__new__(Alberto)
    agent.catalog = SimpleNamespace(get=lambda name: squad)
    agent.personas = SimpleNamespace(get=lambda name: None)
    agent.router = SimpleNamespace(invoke=invoke)

    result = agent.run_squad("resilient", "task")
    assert "provider timed out" in result["outputs"]["first"]
    assert result["outputs"]["second"] == "recovered"


def test_run_squad_falls_back_to_template_when_output_formatting_fails():
    step = SimpleNamespace(persona="analyst", task="{broken", output_to="analysis")
    squad = SimpleNamespace(workflow=[step], personas={})
    agent = Alberto.__new__(Alberto)
    agent.catalog = SimpleNamespace(get=lambda name: squad)
    agent.personas = SimpleNamespace(get=lambda name: None)
    agent.router = SimpleNamespace(invoke=lambda *args, **kwargs: {
        "choices": [{"message": {"content": "ok"}}]
    })

    result = agent.run_squad("template", "task")
    assert result["outputs"]["analysis"] == "ok"



@pytest.mark.parametrize("fallback", [False, True])
def test_chat_keeps_user_turn_last_after_injecting_system_context(monkeypatch, fallback):
    import alberto.agent as agent_module
    import alberto.runtime.smart_router_v2 as smart_router_v2
    import alberto.runtime.skill_engine as skill_engine
    from alberto.conversation import Conversation

    agent = Alberto.__new__(Alberto)
    conversation = Conversation(id="chat-contract", started_at=1.0)

    class Store:
        def get(self, conversation_id):
            return conversation if conversation_id == conversation.id else None

        def latest_active(self, max_age_seconds=600):
            return None

        def create(self):
            return conversation

        def save(self, value):
            assert value is conversation

    agent.conversations = Store()
    agent.catalog = SimpleNamespace(active_squad=None)
    agent.mimo = SimpleNamespace(goal_get=lambda: None)
    strategy = SimpleNamespace(
        mode="solo", squad=None, task_routing="chat", engine="router", reason="test"
    )
    agent.orchestrator = SimpleNamespace(
        decide=lambda prompt, active_squad: strategy
    )
    captured = {}

    def invoke(task, messages, **kwargs):
        captured["messages"] = messages
        return {"choices": [{"message": {"content": "answer"}}]}

    agent.router = SimpleNamespace(invoke=invoke)
    agent._build_integration_context = lambda: "INTEGRATION_CONTEXT"
    agent._supports_function_calling = lambda: False

    monkeypatch.setattr(agent_module, "detect_intent", lambda prompt: {})
    monkeypatch.setattr(agent_module, "recall_memory", lambda _agent, _prompt: "")
    monkeypatch.setattr(agent_module, "ALBERTO_SYSTEM_PROMPT", lambda _agent: "PERSONA")
    monkeypatch.setattr(agent_module, "build_catalog_block", lambda _agent: "CATALOG")
    monkeypatch.setattr(
        agent_module, "build_messages",
        lambda conv, **kwargs: [
            {"role": "system", "content": "PERSONA"},
            {"role": "user", "content": conv.turns[-1].content},
        ],
    )
    monkeypatch.setattr(smart_router_v2, "route_intent", lambda _prompt: {"route": "chat"})
    monkeypatch.setattr(smart_router_v2, "build_route_prompt", lambda _route: "ROUTE_CONTEXT")
    monkeypatch.setattr(skill_engine, "auto_invoke_skill", lambda _prompt: None)
    monkeypatch.setattr(agent_module, "is_fallback_model", lambda _agent: fallback)
    monkeypatch.setattr(agent_module, "get_mavis_takeover_prompt", lambda: "MAVIS_CONTEXT")

    result = agent.chat("inspect this repository", conversation_id="chat-contract")
    messages = captured["messages"]

    if fallback:
        assert "MAVIS FALLBACK MODE" in result["response"]
    else:
        assert result["response"] == "answer"
    assert messages[-1] == {"role": "user", "content": "inspect this repository"}
    system_contents = [m["content"] for m in messages[:-1] if m["role"] == "system"]
    assert "INTEGRATION_CONTEXT" in system_contents
    assert "ROUTE_CONTEXT" in system_contents
    assert ("MAVIS_CONTEXT" in system_contents) is fallback
