"""Opt-in live end-to-end test: real provider, Alberto chat, and real tool execution.

Run:
  ALBERTO_LIVE_TESTS=1 NVIDIA_API_KEY=... python -m pytest -q tests/test_live_agent_conversation.py

This test is intentionally excluded from the offline CI suites. It sends real
requests to the configured NVIDIA OpenAI-compatible endpoint and may incur cost.
"""
import os

import pytest


def test_live_agent_remembers_conversation_and_executes_real_tool(tmp_path, monkeypatch):
    if os.environ.get("ALBERTO_LIVE_TESTS") != "1":
        pytest.skip("set ALBERTO_LIVE_TESTS=1 to opt into paid live-provider tests")
    if not os.environ.get("NVIDIA_API_KEY"):
        pytest.skip("NVIDIA_API_KEY is required for live-provider tests")

    from alberto.agent import Alberto
    from alberto.sandbox import LocalSandbox
    from alberto.runtime.function_caller import run_tool_loop

    model_id = os.environ.get("ALBERTO_LIVE_MODEL_ID", "meta/llama-3.3-70b-instruct")
    sandbox = LocalSandbox(base_dir=tmp_path / "alberto-live-sandbox", allow_net=True)
    agent = Alberto(sandbox=sandbox)

    # Configure the same real remote model for both normal chat and reasoning.
    agent.model_set(
        task="code",
        provider="nvidia",
        model_id=model_id,
        base_url="https://integrate.api.nvidia.com/v1",
        credential_env="NVIDIA_API_KEY",
    )
    agent.model_set(
        task="reasoning",
        provider="nvidia",
        model_id=model_id,
        base_url="https://integrate.api.nvidia.com/v1",
        credential_env="NVIDIA_API_KEY",
    )

    try:
        first = agent.chat(
            "Para este teste de conversa, o código temporário é cobalt-731. "
            "Responde apenas com a palavra PRONTO."
        )
        assert isinstance(first.get("response"), str) and first["response"].strip(), (
            f"Alberto.chat returned no answer: {first!r}"
        )
        conversation_id = first.get("conversation_id")
        assert conversation_id, "Alberto.chat must return a conversation_id"

        follow_up = agent.chat(
            "Qual foi o código temporário que acabei de indicar? "
            "Responde incluindo o código exato.",
            conversation_id=conversation_id,
        )
        answer = follow_up.get("response", "")
        assert "cobalt-731" in answer.lower(), (
            "The live model did not preserve/retrieve the previous turn; "
            f"response={answer!r}"
        )

        # Force an actual provider tool-call round trip. memory_set writes to
        # the real SQLite-backed MiMo memory; no mocked router or tool registry.
        key = "live_integration_probe"
        value = "tool-executed-cobalt-731"
        tool_result = run_tool_loop(
            agent,
            [
                {
                    "role": "system",
                    "content": (
                        "You must use the memory_set tool exactly once with the "
                        "provided key and value. Do not claim success unless the tool "
                        "call is executed."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Call memory_set with key={key!r}, value={value!r}, "
                        "tags='live-integration-test'. Then report the result."
                    ),
                },
            ],
            task="code",
            max_iterations=4,
            max_tokens=512,
            temperature=0,
        )
        assert not tool_result.get("error"), f"Live tool loop failed: {tool_result.get('error')}"
        called = [
            call for call in tool_result.get("tool_calls", [])
            if call.get("function", {}).get("name") == "memory_set"
        ]
        assert called, f"The real model did not invoke memory_set: {tool_result!r}"
        assert agent.memory_get(key) == value, (
            "The tool call was reported but the value was not persisted in real memory"
        )
        assert tool_result.get("final_content"), "No final model response after tool execution"
    finally:
        try:
            agent.hermes.stop()
        finally:
            try:
                agent.mimo.stop()
            finally:
                agent.sandbox.cleanup()
