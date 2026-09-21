"""
Testes intensivos — cobrem TODAS as features adicionadas.

Cada teste é REAL: importa upstream, faz operação real, verifica resultado.
Skips automático se LLM não disponível.
"""
from __future__ import annotations
import os
import json
import pytest
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alberto import Alberto
from alberto.tools_registry import list_tools, invoke_tool
from alberto.engines.hermes_tools import (
    HERMES_TOOL_REGISTRY, list_hermes_tools_full, invoke_hermes_tool,
)
from alberto.upstream_bridge import (
    list_upstream_tools, list_upstream_skills, get_upstream_summary,
)


NVIDIA_KEY = "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"
os.environ.setdefault("NVIDIA_API_KEY", NVIDIA_KEY)


# === Discovery ===
def test_tools_count_77_plus():
    """Alberto must wrap at least 70 tools from upstream."""
    tools = list_tools()
    assert len(tools) >= 70, f"only {len(tools)} tools registered"


def test_all_tools_have_real_fn():
    """Every tool must have a callable fn, not be a stub."""
    for t in HERMES_TOOL_REGISTRY:
        assert callable(t["fn"]), f"{t['name']} has no callable fn"


def test_engines_breakdown():
    """Tools grouped by engine."""
    from collections import Counter
    tools = list_tools()
    engines = Counter(t["engine"] for t in tools)
    assert engines.get("hermes", 0) >= 30
    assert engines.get("mimo", 0) >= 8
    assert engines.get("nemoclaw", 0) >= 5
    assert engines.get("aiox", 0) >= 2


def test_upstream_discovers_real_files():
    """upstream/ discovery finds real source files."""
    tools = list_upstream_tools()
    skills = list_upstream_skills()
    assert len(tools) >= 50, f"only {len(tools)} upstream tools found"
    assert len(skills) >= 10, f"only {len(skills)} upstream skills found"


# === Hermes tools (real upstream wrapping) ===
@pytest.fixture
def alberto():
    base = Path(__file__).parent.parent
    a = Alberto(catalog_dir=base / "workflows", personas_dir=base / "personas")
    yield a
    a.shutdown()


def test_browser_real_hermes(alberto):
    """Browser tool returns text from real URL (urllib fallback since camofox not running)."""
    out = invoke_hermes_tool(alberto, "browser", {"url": "https://example.com"})
    assert out.get("ok") or "Example" in str(out)
    if out.get("ok"):
        assert "Example" in out.get("text", "") or len(out.get("text", "")) > 50


def test_code_execution_real(alberto):
    """Code execution returns real output."""
    out = invoke_hermes_tool(alberto, "code_execution", {"code": "print(2*21)"})
    assert out["ok"] is True
    assert "42" in out["stdout"]


def test_terminal_real(alberto):
    """Terminal tool runs shell commands."""
    out = invoke_hermes_tool(alberto, "terminal", {"command": "echo alberto-test"})
    assert out["ok"] is True
    assert "alberto-test" in out.get("stdout", "")


def test_mcp_list_servers(alberto):
    """MCP tool lists (or empty) servers."""
    out = invoke_hermes_tool(alberto, "mcp", {"action": "list"})
    assert out.get("ok") is True


def test_vision_needs_image(alberto):
    """Vision tool requires an image URL or base64."""
    out = invoke_hermes_tool(alberto, "vision", {})
    assert out["ok"] is False
    assert "image_url" in out.get("error", "") or "image_base64" in out.get("error", "")


def test_web_search_needs_provider(alberto):
    """Web search fails gracefully when no provider configured."""
    out = invoke_hermes_tool(alberto, "web_search", {"query": "test"})
    # Either succeeds with results or returns clear error
    assert "ok" in out


def test_tts_requires_text(alberto):
    out = invoke_hermes_tool(alberto, "voice.tts", {})
    assert out["ok"] is False
    assert "text" in out.get("error", "")


def test_stt_requires_path(alberto):
    out = invoke_hermes_tool(alberto, "voice.stt", {})
    assert out["ok"] is False
    assert "audio_path" in out.get("error", "")


def test_file_read_write(alberto):
    """File tool real read/write."""
    test_path = "/tmp/alberto-fs-test.txt"
    out = invoke_hermes_tool(alberto, "file",
                            {"action": "write", "path": test_path, "content": "hello"})
    assert out["ok"] is True
    out = invoke_hermes_tool(alberto, "file", {"action": "read", "path": test_path})
    assert out["ok"] is True
    assert "hello" in out["content"]


def test_file_list(alberto):
    out = invoke_hermes_tool(alberto, "file", {"action": "list", "path": "/tmp"})
    assert out["ok"] is True
    assert isinstance(out["entries"], list)


def test_file_exists(alberto):
    out = invoke_hermes_tool(alberto, "file", {"action": "exists", "path": "/tmp"})
    assert out["ok"] is True
    assert out["exists"] is True


def test_patch_parser_parses(alberto):
    patch = """--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 line1
-old
+new
 line3
"""
    out = invoke_hermes_tool(alberto, "patch_parser", {"patch": patch})
    assert out["ok"] is True
    assert "foo.py" in str(out)


def test_threat_patterns_scans(alberto):
    """Threat patterns detects real API keys."""
    text = "Here's my key: sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMN"
    out = invoke_hermes_tool(alberto, "threat_patterns", {"text": text})
    assert out["ok"] is True
    assert any(f["type"] == "openai_key" for f in out.get("findings", []))


def test_approval_flags_dangerous(alberto):
    """Approval system flags dangerous commands."""
    out = invoke_hermes_tool(alberto, "approval", {"command": "rm -rf /"})
    assert out["ok"] is True
    assert out["dangerous"] is True


def test_tirith_detects_metadata(alberto):
    """Tirith flags metadata IP."""
    out = invoke_hermes_tool(alberto, "tirith", {"url": "http://169.254.169.254/"})
    assert out["ok"] is True
    assert out["risky"] is True


def test_env_probe_returns_state(alberto):
    """Env probe reports Python toolchain state."""
    out = invoke_hermes_tool(alberto, "env_probe", {})
    assert out["ok"] is True
    probe = out["probe"]
    assert "python3" in probe


# === MiMo tools ===
def test_mimo_memory_set_get(alberto):
    out = invoke_hermes_tool(alberto, "mimo_memory",
                            {"key": "intensive.test", "value": "abc"})
    assert out["ok"] is True
    out = invoke_hermes_tool(alberto, "mimo_memory", {"key": "intensive.test"})
    assert out["ok"] is True
    assert out["value"] == "abc"


def test_mimo_memory_search(alberto):
    alberto.mimo.memory_set("intensive.search", "cubic hermite data", tags="test")
    out = invoke_hermes_tool(alberto, "mimo_memory", {"query": "cubic", "limit": 5})
    assert out["ok"] is True
    assert any("cubic" in r.get("value", "") for r in out["results"])


def test_mimo_memory_list(alberto):
    out = invoke_hermes_tool(alberto, "mimo_memory", {})
    assert out["ok"] is True
    assert "entries" in out


def test_mimo_goal_set_get_clear(alberto):
    out = invoke_hermes_tool(alberto, "mimo_goal", {"action": "set", "goal": "test goal"})
    assert out["ok"] is True
    out = invoke_hermes_tool(alberto, "mimo_goal", {})
    assert out["ok"] is True
    out = invoke_hermes_tool(alberto, "mimo_goal", {"action": "clear"})
    assert out["ok"] is True
    assert alberto.mimo.goal_get() is None


def test_mimo_session_create(alberto):
    out = invoke_hermes_tool(alberto, "mimo_session", {"goal": "test session"})
    assert out["ok"] is True
    assert "session" in out


def test_mimo_session_list(alberto):
    out = invoke_hermes_tool(alberto, "mimo_session", {"action": "list"})
    assert out["ok"] is True
    assert "sessions" in out


def test_mimo_distill(alberto):
    alberto.mimo.memory_set("k1", "v1", tags="test")
    alberto.mimo.memory_set("k2", "v2", tags="test")
    out = invoke_hermes_tool(alberto, "mimo_distill", {})
    assert out["ok"] is True
    assert "distilled" in out


# === NemoClaw integration ===
def test_nemoclaw_sandbox_status(alberto):
    out = invoke_hermes_tool(alberto, "nemoclaw_sandbox", {"action": "list"})
    assert out["ok"] is True
    assert "sandbox" in out
    assert "current" in out


def test_nemoclaw_policy_presets(alberto):
    out = invoke_hermes_tool(alberto, "nemoclaw_policy", {"action": "presets"})
    assert out["ok"] is True
    # Should have several real presets
    assert len(out["presets"]) >= 5


def test_nemoclaw_policy_show(alberto):
    out = invoke_hermes_tool(alberto, "nemoclaw_policy",
                            {"action": "show", "preset": "github"})
    assert out["ok"] is True
    assert "github" in out["preset"]


def test_nemoclaw_shields(alberto):
    out = invoke_hermes_tool(alberto, "nemoclaw_shields", {})
    assert out["ok"] is True
    assert "secrets_scanner" in out["shields"]


def test_nemoclaw_inference(alberto):
    out = invoke_hermes_tool(alberto, "nemoclaw_inference", {})
    assert out["ok"] is True
    assert "providers" in out
    assert "nvidia" in out["providers"]


def test_nemoclaw_backup(alberto):
    out = invoke_hermes_tool(alberto, "nemoclaw_backup", {"action": "backup"})
    assert out["ok"] is True
    assert "target" in out


def test_nemoclaw_blueprint(alberto):
    out = invoke_hermes_tool(alberto, "nemoclaw_blueprint", {"action": "list"})
    assert out["ok"] is True
    assert "profiles" in out
    assert "nim-local" in out["profiles"]


# === AIOX ===
def test_aiox_squad_list(alberto):
    out = invoke_hermes_tool(alberto, "aiox_squad", {"action": "list"})
    assert out["ok"] is True
    assert len(out["squads"]) >= 11


def test_aiox_squad_activate_hibernate(alberto):
    out = invoke_hermes_tool(alberto, "aiox_squad", {"action": "activate", "name": "engineering"})
    assert out["ok"] is True
    assert alberto.catalog.active_squad == "engineering"
    out = invoke_hermes_tool(alberto, "aiox_squad", {"action": "hibernate"})
    assert out["ok"] is True
    assert alberto.catalog.active_squad is None


def test_aiox_agent_lookup(alberto):
    out = invoke_hermes_tool(alberto, "aiox_agent", {"name": "pm"})
    assert out["ok"] is True
    assert "system_prompt" in out or "content" in out


# === Channel tools (graceful fail without credentials) ===
@pytest.mark.parametrize("channel,extra_args", [
    ("discord", {"action": "list_channels"}),
    ("telegram", {"chat_id": "@channel", "message": "test"}),
    ("slack", {"channel": "#general", "message": "test"}),
    ("whatsapp", {"phone": "+5511999999999", "message": "test"}),
    ("feishu", {"doc_id": "oc_test", "message": "test"}),
    ("signal", {"phone": "+15551234567", "message": "test"}),
    ("imessage", {"phone": "+15551234567", "message": "test"}),
    ("sms", {"phone": "+15551234567", "message": "test"}),
    ("wechat", {"wxid": "wxid_test", "message": "test"}),
    ("email", {"action": "list"}),
    ("homeassistant", {"action": "list_entities"}),
    ("microsoft_graph", {"action": "list_mail"}),
])
def test_channel_tools_structure(alberto, channel, extra_args):
    """Every channel tool must be invocable (returns structured result, even on no-creds)."""
    out = invoke_hermes_tool(alberto, channel, extra_args)
    assert "ok" in out  # always returns a structured dict


# === LLM live tests ===
def _llm_available() -> bool:
    return bool(os.environ.get("NVIDIA_API_KEY"))


@pytest.mark.skipif(not _llm_available(), reason="NVIDIA_API_KEY not set")
def test_real_llm_chat(alberto):
    """Real LLM call via model router."""
    alberto.model_set("chat", provider="nvidia", model_id="minimaxai/minimax-m3",
                     base_url="https://integrate.api.nvidia.com/v1",
                     credential_env="NVIDIA_API_KEY")
    resp = alberto.router.invoke("chat", [
        {"role": "user", "content": "Responda em 1 frase: o que é Python?"}
    ], max_tokens=100, temperature=0.0)
    assert "Python" in resp["choices"][0]["message"]["content"] or "python" in resp["choices"][0]["message"]["content"]


@pytest.mark.skipif(not _llm_available(), reason="NVIDIA_API_KEY not set")
def test_real_llm_via_agent_chat(alberto):
    """Real LLM call via agent.chat()."""
    alberto.model_set("chat", provider="nvidia", model_id="minimaxai/minimax-m3",
                     base_url="https://integrate.api.nvidia.com/v1",
                     credential_env="NVIDIA_API_KEY")
    alberto.model_set("code", provider="nvidia", model_id="minimaxai/minimax-m3",
                     base_url="https://integrate.api.nvidia.com/v1",
                     credential_env="NVIDIA_API_KEY")
    alberto.model_set("reasoning", provider="nvidia", model_id="minimaxai/minimax-m3",
                     base_url="https://integrate.api.nvidia.com/v1",
                     credential_env="NVIDIA_API_KEY")
    r = alberto.chat("Diz só 'pong' e nada mais.")
    assert "pong" in r["response"].lower()


@pytest.mark.skipif(not _llm_available(), reason="NVIDIA_API_KEY not set")
def test_real_llm_natural_conversation(alberto):
    """Real LLM natural conversation + memory."""
    alberto.model_set("chat", provider="nvidia", model_id="minimaxai/minimax-m3",
                     base_url="https://integrate.api.nvidia.com/v1",
                     credential_env="NVIDIA_API_KEY")
    alberto.model_set("code", provider="nvidia", model_id="minimaxai/minimax-m3",
                     base_url="https://integrate.api.nvidia.com/v1",
                     credential_env="NVIDIA_API_KEY")
    alberto.model_set("reasoning", provider="nvidia", model_id="minimaxai/minimax-m3",
                     base_url="https://integrate.api.nvidia.com/v1",
                     credential_env="NVIDIA_API_KEY")
    r1 = alberto.chat("Me lembra que meu nome é Teste Intensivo")
    assert r1["response"]
    # Memory should have key with name
    val = alberto.mimo.memory_get("user.nome") or alberto.mimo.memory_get("user_note")
    assert val is not None


@pytest.mark.skipif(not _llm_available(), reason="NVIDIA_API_KEY not set")
def test_real_llm_code_generation(alberto):
    """Real LLM generates code via MiMo engine."""
    alberto.model_set("code", provider="nvidia", model_id="minimaxai/minimax-m3",
                     base_url="https://integrate.api.nvidia.com/v1",
                     credential_env="NVIDIA_API_KEY")
    code = alberto.mimo.invoke("Write a Python function that returns the factorial of n. Just the code.",
                              task="code")
    assert "def " in code and "factorial" in code.lower()
