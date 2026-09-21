"""
Smoke tests for Alberto AI v1.0.

Covers:
- identity, agent, status
- memory (FTS5)
- shortcuts (JSON persistence)
- squad catalog (YAML)
- persona registry (.md)
- orchestrator (strategy decision)
- hermes (browser-disabled, code-execution, cron)
- tools registry
- server routes (mocked)
- new personas (scrum, data-engineer, ml-engineer, etc.)
- new squads (data-ml, growth, finance, support, etc.)

Runs WITHOUT any LLM API access.
"""
from __future__ import annotations
import json
import os
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alberto.agent import Alberto
from alberto.identity import NAME, VERSION, get_banner
from alberto.model_router import ModelConfig, ModelSpec
from alberto.orchestrator import Orchestrator
from alberto.tools_registry import list_tools, invoke_tool


@pytest.fixture
def alberto():
    base = Path(__file__).parent.parent
    a = Alberto(catalog_dir=base / "workflows", personas_dir=base / "personas")
    yield a
    a.shutdown()


# ===== Identity =====
def test_identity():
    assert NAME == "Alberto AI"
    assert VERSION == "1.0.0"
    assert "Alberto" in get_banner()


# ===== Agent =====
def test_agent_status(alberto):
    s = alberto.status()
    assert s["name"] == "Alberto AI"
    assert s["mimo"]["running"] is True
    total_squads = len(s.get("squads_alberto", [])) + len(s.get("squads_aiox", []))
    assert total_squads >= 11


# ===== Memory =====
def test_memory_persistence(alberto):
    alberto.memory_set("user.name", "Test User", tags="user")
    alberto.memory_set("user.email", "test@example.com", tags="user")
    assert alberto.memory_get("user.name") == "Test User"
    hits = alberto.memory_search("alberto")
    alberto.memory_set("project.alberto", "Alberto AI", tags="project")
    hits = alberto.memory_search("alberto")
    assert any(h["key"] == "project.alberto" for h in hits)


def test_memory_distill(alberto):
    alberto.memory_set("k1", "value 1", tags="test")
    alberto.memory_set("k2", "value 2", tags="test")
    text = alberto.mimo.distill()
    assert isinstance(text, str)


# ===== Shortcuts =====
def test_shortcuts_add_use_remove(alberto):
    alberto.shortcuts.add("ms", "memory search {{args}}")
    alberto.shortcuts.add("gdp", "hermes exec 'git diff'")
    assert alberto.shortcut_expand("ms", "alberto") == "memory search alberto"
    sc = alberto.shortcuts.get("ms")
    assert sc.use_count == 1
    assert alberto.shortcuts.remove("ms") is True


def test_shortcut_persistence_across_instances(alberto):
    alberto.shortcuts.add("foo", "bar {{args}}")
    a2 = Alberto(
        catalog_dir=Path(__file__).parent.parent / "workflows",
        personas_dir=Path(__file__).parent.parent / "personas",
        sandbox=alberto.sandbox,
    )
    try:
        sc = a2.shortcuts.get("foo")
        assert sc is not None
        assert sc.expansion == "bar {{args}}"
    finally:
        a2.shutdown()


# ===== Squads =====
def test_squad_catalog_loaded(alberto):
    squads = alberto.squad_list()
    expected = {"engineering", "research", "product", "incident",
                "data-ml", "growth", "finance", "support",
                "ml-ops", "content", "sales"}
    assert expected.issubset(set(squads)), f"missing: {expected - set(squads)}"


def test_squad_describe_engineering(alberto):
    d = alberto.squad_describe("engineering")
    assert d["name"] == "engineering"
    assert len(d["workflow"]) == 5


def test_squad_describe_data_ml(alberto):
    d = alberto.squad_describe("data-ml")
    assert d is not None
    assert "analyst" in d["personas"]
    assert "data_engineer" in d["personas"]
    assert "ml_engineer" in d["personas"]
    assert "mlops" in d["personas"]
    assert "sre" in d["personas"]


def test_squad_describe_growth(alberto):
    d = alberto.squad_describe("growth")
    assert d is not None
    assert "growth" in d["personas"]
    assert "analyst" in d["personas"]


def test_squad_describe_finance(alberto):
    d = alberto.squad_describe("finance")
    assert d is not None
    assert "finance" in d["personas"]


def test_squad_activate_hibernate(alberto):
    alberto.squad_activate("data-ml")
    assert alberto.catalog.active_squad == "data-ml"
    alberto.squad_hibernate()
    assert alberto.catalog.active_squad is None


# ===== Personas =====
def test_personas_loaded(alberto):
    names = alberto.personas.list()
    expected = {
        # originals
        "pm", "dev", "qa", "devops", "architect", "analyst",
        "ux_designer", "security", "tech_writer", "sre",
        "critic", "researcher", "ux_researcher",
        # new
        "scrum_master", "data_engineer", "ml_engineer", "growth",
        "finance", "sales", "support", "content", "recruiter", "mentor",
    }
    missing = expected - set(names)
    assert not missing, f"missing personas: {missing}"


# ===== Orchestrator =====
def test_orchestrator_decides_solo(alberto):
    o = Orchestrator()
    s = o.decide("hello world", active_squad=None)
    assert s.mode == "solo"
    assert s.engine == "mimo"


def test_orchestrator_decides_speculative(alberto):
    o = Orchestrator()
    s = o.decide("what's the best approach here?", active_squad=None)
    assert s.mode == "speculative"
    s = o.decide("use max mode", active_squad=None)
    assert s.mode == "speculative"


def test_orchestrator_decides_squad(alberto):
    o = Orchestrator()
    s = o.decide("anything", active_squad="data-ml")
    assert s.mode == "squad"
    assert s.squad == "data-ml"


def test_orchestrator_decides_hermes(alberto):
    o = Orchestrator()
    s = o.decide("anything", hermes_command="browser")
    assert s.engine == "hermes"


# ===== Model router =====
def test_model_router_no_default():
    cfg = ModelConfig(tasks={}, fallback_chain=[])
    assert cfg.resolve("anything") is None


def test_model_router_set_and_resolve():
    cfg = ModelConfig(tasks={}, fallback_chain=[])
    cfg.set_task("chat", ModelSpec(
        provider="nvidia", model_id="user-chosen",
        base_url="https://example.com", credential_env="EXAMPLE_API_KEY",
    ))
    spec = cfg.resolve("chat")
    assert spec.provider == "nvidia"


# ===== Dispatch + squad run =====
def test_dispatch_routes_to_correct_strategy(alberto):
    o = Orchestrator()
    s = o.decide("hello world", active_squad=None)
    assert s.mode == "solo"
    s = o.decide("what's the best way?", active_squad=None)
    assert s.mode == "speculative"


def test_squad_run_with_fake_llm(monkeypatch, alberto):
    def fake_invoke(task, messages, **kw):
        return {"choices": [{"message": {"content": f"[fake {task}] {messages[-1]['content'][:60]}"}}]}
    monkeypatch.setattr(alberto.router, "invoke", fake_invoke)
    out = alberto.run_squad("engineering", "build a counter")
    assert "outputs" in out
    assert len(out["outputs"]) == 5


# ===== Hermes =====
def test_hermes_browser_disabled(alberto):
    """Hermes browser calls real upstream code; with no network it fails gracefully."""
    alberto2 = Alberto(
        catalog_dir=Path(__file__).parent.parent / "workflows",
        personas_dir=Path(__file__).parent.parent / "personas",
        sandbox=alberto.sandbox,
    )
    out = alberto2.hermes.browser("https://invalid-domain-xyz-12345.example/")
    # Either browser failed (no real browser lib) or upstream tool returned error
    assert isinstance(out, str)
    alberto2.shutdown()


def test_hermes_code_execution(alberto):
    result = alberto.hermes.code_execution("print(2 + 2)")
    assert result["returncode"] == 0
    assert "4" in result["stdout"]


def test_hermes_cron_register(alberto):
    alberto.hermes.start()
    alberto.hermes.cron_register("test-job", "every 1s", lambda: None)
    jobs = alberto.hermes.cron_list()
    assert any(j["name"] == "test-job" for j in jobs)
    alberto.hermes.cron_remove("test-job")


# ===== Tools registry =====
def test_tools_registry_has_expected_count():
    tools = list_tools()
    assert len(tools) >= 30  # 18 MiMo + 14 Hermes


def test_tools_registry_includes_voice_image_video_x():
    tools = list_tools()
    names = {t["name"] for t in tools}
    assert "voice.tts" in names
    assert "voice.stt" in names
    assert "image.gen" in names
    assert "video.gen" in names
    assert "x_search" in names


def test_tools_registry_includes_worktree_snapshot():
    """Real tools from upstream — worktree, snapshot, code_execution, browser, tts, etc."""
    tools = list_tools()
    names = {t["name"] for t in tools}
    assert "mimo_worktree" in names
    assert "mimo_snapshot" in names
    assert "mimo_snapshot" in names
    assert "code_execution" in names
    assert "browser" in names
    assert "voice.tts" in names


def test_tool_invoke_memory_set(alberto):
    out = invoke_tool(alberto, "mimo_memory", {"key": "test.tool", "value": "ok", "tags": "t"})
    assert out["ok"] is True
    assert alberto.memory_get("test.tool") == "ok"


def test_tool_invoke_memory_search(alberto):
    alberto.memory_set("findme.key", "alpha", tags="test")
    out = invoke_tool(alberto, "mimo_memory", {"query": "alpha", "limit": 5})
    assert out["ok"] is True
    assert any(r.get("value") == "alpha" for r in out["results"])


def test_tool_invoke_unknown(alberto):
    out = invoke_tool(alberto, "nope.does.not.exist", {})
    assert out["ok"] is False


def test_tool_invoke_code_execution(alberto):
    out = invoke_tool(alberto, "code_execution", {"code": "print(7*6)"})
    assert out["ok"] is True
    assert "42" in out["stdout"]


def test_tool_invoke_judge_without_model(alberto):
    """Without a model, judge returns 'unknown' verdict but doesn't crash."""
    out = invoke_tool(alberto, "mimo_goal", {"candidate": "x" * 100})
    assert out["ok"] is True
    assert "verdict" in out


def test_tool_invoke_file_upload(alberto):
    """File write to sandbox."""
    out = invoke_tool(alberto, "file", {"action": "write", "path": "/tmp/test.txt", "content": "hello world"})
    assert out["ok"] is True
    # Verify the file was actually written
    r = invoke_tool(alberto, "file", {"action": "read", "path": "/tmp/test.txt"})
    assert r["ok"] is True
    assert "hello world" in r["content"]


# ===== Server routes =====
@pytest.fixture
def server():
    from fastapi.testclient import TestClient
    from alberto.server import create_app
    base = Path(__file__).parent.parent
    app = create_app(
        alberto=Alberto(catalog_dir=base / "workflows", personas_dir=base / "personas"),
        frontend_dir=base / "frontend",
    )
    return TestClient(app)


def test_server_status(server):
    r = server.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Alberto AI"


def test_server_banner(server):
    r = server.get("/api/banner")
    assert r.status_code == 200
    assert "Alberto AI" in r.json()["text"]


def test_server_squad_list(server):
    r = server.get("/api/squad/list")
    assert r.status_code == 200
    names = r.json()
    assert "engineering" in names
    assert "data-ml" in names


def test_server_memory_set_get(server):
    r = server.post("/api/memory/set", json={"key": "srv.test", "value": "hello"})
    assert r.status_code == 200
    r = server.get("/api/memory/get", params={"key": "srv.test"})
    assert r.status_code == 200
    assert r.json()["value"] == "hello"


def test_server_squad_activate_hibernate(server):
    r = server.post("/api/squad/activate", json={"name": "engineering"})
    assert r.status_code == 200
    assert r.json()["active"] == "engineering"
    r = server.post("/api/squad/hibernate")
    assert r.status_code == 200


def test_server_shortcut_add_list_remove(server):
    r = server.post("/api/shortcut/add", json={"key": "testk", "expansion": "echo {{args}}"})
    assert r.status_code == 200
    r = server.get("/api/shortcut/list")
    assert "testk" in r.json()
    r = server.request("DELETE", "/api/shortcut/remove", params={"key": "testk"})
    assert r.status_code == 200


def test_server_tools_list(server):
    r = server.get("/api/tools/list")
    assert r.status_code == 200
    tools = r.json()
    assert len(tools) >= 30
    assert any(t["name"] == "voice.tts" for t in tools)


def test_server_strategy(server):
    r = server.get("/api/strategy", params={"prompt": "build a counter"})
    assert r.status_code == 200
    data = r.json()
    assert "mode" in data
    assert data["mode"] in ("solo", "speculative", "squad")


def test_server_hermes_exec(server):
    r = server.post("/api/hermes/exec", json={"code": "print('alberto')"})
    assert r.status_code == 200
    assert "alberto" in r.json()["stdout"]


def test_server_frontend_index(server):
    r = server.get("/")
    assert r.status_code == 200
    assert b"Alberto AI" in r.content


def test_server_frontend_css(server):
    r = server.get("/css/main.css")
    assert r.status_code == 200
    assert b"--primary" in r.content


def test_server_frontend_js(server):
    r = server.get("/js/app.js")
    assert r.status_code == 200


def test_server_frontend_bg3d(server):
    r = server.get("/js/bg3d.js")
    assert r.status_code == 200
    assert b"Background3D" in r.content


# ===== Banners and renders =====
def test_banner_renders(alberto):
    b = alberto.banner()
    assert "Alberto AI" in b
    assert "NemoClaw" in b
    assert "MiMo" in b


def test_hermes_strip_html():
    from alberto.engines.hermes import HermesEngine
    h = HermesEngine.__new__(HermesEngine)
    out = h._strip_html("<p>hello <b>world</b></p><script>x</script>")
    assert "hello" in out
    assert "world" in out
    assert "x" not in out