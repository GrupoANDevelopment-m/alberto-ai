"""Opt-in live end-to-end test: real NVIDIA provider, Alberto chat, and real tool execution.

Run:
  ALBERTO_LIVE_TESTS=1 NVIDIA_API_KEY=... python -m pytest -q tests/test_live_agent_conversation.py

Uses NVIDIA's documented Nemotron sampling settings. This test sends real requests
and may incur provider cost; credentials are read only from the environment.
"""
import os

import pytest


def test_live_agent_remembers_conversation_and_executes_real_tool(tmp_path, monkeypatch):
    if os.environ.get("ALBERTO_LIVE_TESTS") != "1":
        pytest.skip("set ALBERTO_LIVE_TESTS=1 to opt into paid live-provider tests")
    if not os.environ.get("NVIDIA_API_KEY"):
        pytest.skip("NVIDIA_API_KEY is required for live-provider tests")

    from openai import OpenAI

    from alberto.agent import Alberto
    from alberto.sandbox import LocalSandbox
    from alberto.runtime.function_caller import run_tool_loop

    model_id = os.environ.get("ALBERTO_LIVE_MODEL_ID", "nvidia/nemotron-3.5-lightning-30b-a3b")

    # First isolate provider connectivity/auth/model availability from Alberto's
    # router. This direct request is intentionally the first network operation.
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.environ["NVIDIA_API_KEY"],
        timeout=45.0,
        max_retries=0,
    )
    probe = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "user", "content": "Reply with exactly: NVIDIA_API_OK"}
        ],
        temperature=1.0,
        top_p=0.95,
        max_tokens=64,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
    )
    assert probe.choices and probe.choices[0].message, (
        f"NVIDIA API returned no chat choice for model {model_id!r}"
    )
    probe_text = probe.choices[0].message.content or ""
    assert probe_text.strip(), (
        f"NVIDIA API endpoint responded but returned empty content for {model_id!r}; "
        f"finish_reason={probe.choices[0].finish_reason!r}"
    )
    client.close()
    sandbox = LocalSandbox(base_dir=tmp_path / "alberto-live-sandbox", allow_net=True)
    agent = Alberto(sandbox=sandbox)

    # Nemotron 3.5 hosted API recommends temperature=1, top_p=0.95 and
    # explicitly supports chat_template_kwargs for reasoning control.
    nvidia_options = {
        "temperature": 1.0,
        "top_p": 0.95,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    for task in ("code", "reasoning"):
        agent.model_set(
            task=task,
            provider="nvidia",
            model_id=model_id,
            base_url="https://integrate.api.nvidia.com/v1",
            credential_env="NVIDIA_API_KEY",
            **nvidia_options,
        )

    try:
        first = agent.chat(
            "Para este teste de conversa, o código temporário é cobalt-731. "
            "Responde apenas com a palavra PRONTO."
        )
        first_answer = first.get("response", "")
        assert isinstance(first_answer, str) and first_answer.strip(), (
            f"Alberto.chat returned no answer: {first!r}"
        )
        assert not first_answer.startswith("[sem modelo configurado"), (
            f"Provider/router error was returned as chat content: {first_answer}"
        )
        assert not first_answer.startswith("[tool loop failed"), (
            f"Tool-loop error was returned as chat content: {first_answer}"
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

        # Real provider tool-call round trip; no mocked router or tool registry.
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
            max_tokens=1024,
            temperature=1.0,
        )
        assert not tool_result.get("error"), (
            f"Live tool loop failed: {tool_result.get('error')}; "
            f"tool_result={tool_result!r}"
        )
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
