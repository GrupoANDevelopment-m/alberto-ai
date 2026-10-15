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
