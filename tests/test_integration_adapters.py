"""Unit tests for integration adapters and defensive fallback behavior."""
import subprocess
from types import SimpleNamespace

import pytest

from alberto.runtime import integration


def test_hermes_tool_exists_for_present_and_missing_tools(monkeypatch):
    from alberto.engines import hermes_tools

    monkeypatch.setattr(hermes_tools, "tool_test_probe", lambda *_: "ok", raising=False)
    assert integration.hermes_tool_exists("test_probe") is True
    assert integration.hermes_tool_exists("tool_that_does_not_exist_987") is False


def test_hermes_tool_exists_fails_closed_when_import_breaks(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "alberto.engines":
            raise ImportError("simulated import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    assert integration.hermes_tool_exists("terminal") is False


@pytest.mark.parametrize(
    ("result", "expected", "is_error"),
    [
        ({"ok": True, "output": "from output"}, "from output", False),
        ({"ok": True, "content": "from content"}, "from content", False),
        ({"ok": True, "result": "from result"}, "from result", False),
        ({"ok": True}, '{"ok": true}', False),
        ({"ok": False, "error": "denied"}, "hermes sample: denied", True),
        ({"ok": False}, "hermes sample: unknown error", True),
        ("plain result", "plain result", False),
    ],
)
def test_invoke_hermes_tool_normalizes_return_shapes(monkeypatch, result, expected, is_error):
    from alberto.engines import hermes_tools

    monkeypatch.setattr(hermes_tools, "tool_sample", lambda *_: result, raising=False)
    output, error = integration.invoke_hermes_tool(None, "sample", {})
    assert output == expected
    assert error is is_error


def test_invoke_hermes_tool_handles_missing_tool():
    output, error = integration.invoke_hermes_tool(None, "missing_probe_987", {})
    assert error is True
    assert "not found" in output


def test_invoke_hermes_tool_truncates_long_output(monkeypatch):
    from alberto.engines import hermes_tools

    monkeypatch.setattr(hermes_tools, "tool_long_probe", lambda *_: "x" * 5000, raising=False)
    output, error = integration.invoke_hermes_tool(None, "long_probe", {})
    assert error is False
    assert len(output) == 3000


def test_invoke_hermes_tool_converts_exceptions_to_errors(monkeypatch):
    from alberto.engines import hermes_tools

    def explode(*_):
        raise RuntimeError("adapter failed")

    monkeypatch.setattr(hermes_tools, "tool_boom_probe", explode, raising=False)
    output, error = integration.invoke_hermes_tool(None, "boom_probe", {})
    assert error is True
    assert "adapter failed" in output


def test_list_aiox_workflows_returns_a_list():
    workflows = integration.list_aiox_workflows()
    assert isinstance(workflows, list)
    assert all(isinstance(item, str) for item in workflows)


def test_run_aiox_workflow_reports_missing_workflow():
    result = integration.run_aiox_workflow("workflow_that_does_not_exist_987", None)
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_run_aiox_workflow_never_reports_skipped_steps_as_success():
    workflows = integration.list_aiox_workflows()
    if not workflows:
        pytest.skip("No AIOX workflow YAML files in this checkout")
    # list_aiox_workflows returns filenames including the YAML extension.
    result = integration.run_aiox_workflow(workflows[0], None)
    assert result["ok"] is False
    assert result["status"] == "not_executed"
    assert result["workflow"] == __import__("pathlib").Path(workflows[0]).stem
    assert "not executed" in result["error"].lower()
    assert all(step["status"] == "not_executed" for step in result["steps"])


def test_run_aiox_workflow_rejects_path_traversal():
    result = integration.run_aiox_workflow("../../README", None)
    assert result["ok"] is False
    assert "not found" in result["error"]


@pytest.mark.parametrize(
    ("returncode", "expected"),
    [(0, True), (1, False)],
)
def test_is_docker_available_uses_command_result(monkeypatch, returncode, expected):
    monkeypatch.setattr(
        integration.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=returncode),
    )
    assert integration.is_docker_available() is expected


@pytest.mark.parametrize(
    "exception",
    [FileNotFoundError(), subprocess.TimeoutExpired(cmd="docker version", timeout=5)],
)
def test_is_docker_available_handles_missing_or_timed_out_docker(monkeypatch, exception):
    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(integration.subprocess, "run", fail)
    assert integration.is_docker_available() is False


def test_maybe_use_nemoclaw_preserves_existing_sandbox_when_docker_unavailable(monkeypatch):
    sandbox = object()
    agent = SimpleNamespace(sandbox=sandbox)
    monkeypatch.setattr(
        integration, "nemoclaw_sandbox_status",
        lambda: {"docker_available": False},
    )
    assert integration.maybe_use_nemoclaw(agent, prefer_nemoclaw=True) is sandbox


def test_is_fallback_model_handles_missing_spec():
    assert integration.is_fallback_model(SimpleNamespace(router=SimpleNamespace(
        config=SimpleNamespace(resolve=lambda _task: None)
    ))) is False


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("google/diffusiongemma-26b-a4b-it", True),
        ("google/gemma-2", True),
        ("deepseek-ai/deepseek-v4-pro", False),
        ("openai/gpt-model", False),
    ],
)
def test_is_fallback_model_classifies_model_id(model_id, expected):
    agent = SimpleNamespace(router=SimpleNamespace(
        config=SimpleNamespace(resolve=lambda _task: SimpleNamespace(model_id=model_id))
    ))
    assert integration.is_fallback_model(agent) is expected


def test_is_fallback_model_handles_router_exceptions():
    agent = SimpleNamespace(router=SimpleNamespace(
        config=SimpleNamespace(resolve=lambda _task: (_ for _ in ()).throw(RuntimeError("router down")))
    ))
    assert integration.is_fallback_model(agent) is False


def test_list_vision_models_has_required_fields():
    models = integration.list_vision_models()
    assert len(models) >= 3
    assert all({"id", "lang", "max_tokens"} <= set(model) for model in models)


def test_get_mavis_takeover_prompt_warns_against_fabricated_tool_execution():
    prompt = integration.get_mavis_takeover_prompt()
    assert "DO NOT pretend to execute tools" in prompt
    assert "Comando:" in prompt


def test_call_vision_requires_provider_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    result = integration.call_vision(None, "describe image", "https://example.invalid/image.png")
    assert result == {"ok": False, "error": "NVIDIA_API_KEY not set"}


def test_call_vision_parses_successful_json_response(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(
        "requests.post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: {"choices": [{"message": {
                "content": "visible answer", "reasoning_content": "reasoning"
            }}], "usage": {"total_tokens": 12}},
        ),
    )
    result = integration.call_vision(None, "describe image", "https://example.invalid/image.png")
    assert result["ok"] is True
    assert result["content"] == "visible answer"
    assert result["thinking"] == "reasoning"
    assert result["usage"]["total_tokens"] == 12


def test_call_vision_returns_provider_error_status(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(
        "requests.post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=503, json=lambda: {"detail": "temporarily unavailable"}
        ),
    )
    result = integration.call_vision(None, "describe image", "https://example.invalid/image.png")
    assert result["ok"] is False
    assert result["status"] == 503
    assert "temporarily unavailable" in result["error"]


def test_call_vision_converts_transport_exception_to_error(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def fail(*args, **kwargs):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr("requests.post", fail)
    result = integration.call_vision(None, "describe image", "https://example.invalid/image.png")
    assert result["ok"] is False
    assert "provider timeout" in result["error"]


def test_setup_fallback_chain_configures_routes_and_fallbacks():
    class Config:
        def __init__(self):
            self.fallbacks = []

        def add_fallback(self, spec):
            self.fallbacks.append(spec)

    class Router:
        def __init__(self):
            self.tasks = {}
            self.config = Config()

        def set_task(self, task, spec):
            self.tasks[task] = spec

    agent = SimpleNamespace(router=Router())
    assert integration.setup_fallback_chain(agent) is True
    assert {"code", "chat", "reasoning", "multimodal"} == set(agent.router.tasks)
    assert len(agent.router.config.fallbacks) == 2
    assert agent.router.config.fallbacks[0].options["supports_function_calling"] is False
    assert agent.router.config.fallbacks[1].options["reasoning_effort"] == "max"


def test_setup_fallback_chain_returns_false_on_router_failure():
    agent = SimpleNamespace(router=SimpleNamespace(
        set_task=lambda *_: (_ for _ in ()).throw(RuntimeError("route config failed"))
    ))
    assert integration.setup_fallback_chain(agent) is False


def test_nemoclaw_sandbox_status_reports_docker_and_paths(monkeypatch):
    monkeypatch.setattr(integration, "is_docker_available", lambda: True)
    result = integration.nemoclaw_sandbox_status()
    assert result["docker_available"] is True
    assert result["fallback"] == "NemoClaw"
    assert isinstance(result["nemoclaw_cli_installed"], bool)
    assert isinstance(result["nemoclaw_source_available"], bool)


def test_call_multimodal_kimi_returns_stream_chunks(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    class Response:
        def iter_lines(self):
            return [b"data: first", b"", b"data: second"]

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: Response())
    result = integration.call_multimodal_kimi(None, "describe", "https://example.invalid/image.png")
    assert result["ok"] is True
    assert result["chunks"] == ["data: first", "data: second"]
    assert result["full"] == "data: first\ndata: second"


def test_call_multimodal_kimi_converts_transport_exception(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("multimodal timeout")

    monkeypatch.setattr("requests.post", fail)
    result = integration.call_multimodal_kimi(None, "describe", "https://example.invalid/image.png")
    assert result["ok"] is False
    assert "multimodal timeout" in result["error"]
