"""Behavioral contracts for Hermes wrapper dispatch and failure handling."""

from types import SimpleNamespace

from alberto.engines import hermes_tools


def test_dispatch_passes_agent_context_to_unbound_contextual_callable(monkeypatch):
    agent = object()
    seen = []

    def execute(self, *, target):
        seen.append((self, target))
        return {"ok": True, "target": target}

    monkeypatch.setattr(
        hermes_tools, "_try_import",
        lambda name: SimpleNamespace(execute=execute) if name == "context_tool" else None,
    )
    runner = hermes_tools._tool_fn_or_error(
        [("context_tool", ["execute"])], "install context tool"
    )

    result = runner(agent, {"target": "workspace"})

    assert result == {"ok": True, "target": "workspace"}
    assert seen == [(agent, "workspace")]


def test_dispatch_does_not_retry_callable_after_internal_type_error(monkeypatch):
    calls = []
    agent = object()

    def execute(self=None, *, action):
        calls.append((self, action))
        raise TypeError("internal tool bug after side effect")

    monkeypatch.setattr(
        hermes_tools, "_try_import",
        lambda name: SimpleNamespace(execute=execute) if name == "context_tool" else None,
    )
    runner = hermes_tools._tool_fn_or_error(
        [("context_tool", ["execute"]), ("fallback_tool", ["execute"])],
        "check tool installation",
    )

    result = runner(agent, {"action": "write"})

    assert calls == [(agent, "write")]
    assert result["ok"] is False
    assert "internal tool bug after side effect" in result["error"]
    assert result["modules_tried"] == ["context_tool", "fallback_tool"]


def test_dispatch_falls_through_when_module_or_attribute_is_unavailable(monkeypatch):
    def execute(*, value):
        return {"ok": True, "value": value}

    monkeypatch.setattr(
        hermes_tools, "_try_import",
        lambda name: None if name == "missing_tool" else SimpleNamespace(execute=execute),
    )
    runner = hermes_tools._tool_fn_or_error(
        [("missing_tool", ["execute"]), ("available_tool", ["not_here", "execute"])],
        "install tool",
    )

    assert runner(object(), {"value": 7}) == {"ok": True, "value": 7}



import pytest


@pytest.mark.parametrize(
    ("raw_args", "expected_error"),
    [
        ("{malformed", "invalid tool arguments JSON"),
        ("[]", "expected a JSON object"),
        ('"string"', "expected a JSON object"),
        ("null", "expected a JSON object"),
    ],
)
def test_tool_loop_rejects_malformed_or_non_object_arguments_without_dispatch(
    monkeypatch, raw_args, expected_error
):
    calls = []
    responses = [
        {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call-invalid",
                        "type": "function",
                        "function": {
                            "name": "dangerous_test",
                            "arguments": raw_args,
                        },
                    }],
                }
            }]
        },
        {"choices": [{"message": {"content": "handled safely", "tool_calls": []}}]},
    ]

    def dangerous(_agent, _args):
        calls.append("executed")
        return {"ok": True}

    monkeypatch.setitem(hermes_tools.TOOL_REGISTRY, "dangerous_test", dangerous)

    class Router:
        def invoke(self, *args, **kwargs):
            return responses.pop(0)

    from alberto.runtime.function_caller import run_tool_loop

    result = run_tool_loop(SimpleNamespace(router=Router()), [{"role": "user", "content": "run"}])

    assert result["final_content"] == "handled safely"
    assert calls == []
    tool_messages = [m for m in result["history"] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "[dangerous_test ERROR]" in tool_messages[0]["content"]
    assert expected_error in tool_messages[0]["content"]


def test_tool_loop_reports_router_failure_with_bounded_history():
    from alberto.runtime.function_caller import run_tool_loop

    class BrokenRouter:
        def invoke(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    result = run_tool_loop(
        SimpleNamespace(router=BrokenRouter()),
        [{"role": "user", "content": "run"}],
        max_iterations=3,
    )

    assert result["iterations"] == 1
    assert "provider unavailable" in result["error"]
    assert result["history"] == [{"role": "user", "content": "run"}]
