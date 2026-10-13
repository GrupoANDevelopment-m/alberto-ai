"""MiMo application-generation integration regression tests."""
from pathlib import Path
from types import SimpleNamespace

from alberto.engines.hermes_tools import _mimo_app_create, HERMES_TOOL_REGISTRY


def test_mimo_app_create_runs_plan_then_materializes_scaffold(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    calls = []

    class Mimo:
        def compose(self, spec, *, steps):
            calls.append((spec, steps))
            return {
                "spec": {"content": "Requirements and architecture"},
                "tdd": {"content": "Acceptance test plan"},
                "review": {"content": "Security review"},
            }

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "mimo-demo", "spec": "A small task manager"})

    assert result["ok"] is True
    assert result["engine"] == "MiMo"
    assert result["planning_steps"] == ["spec", "tdd", "review"]
    assert len(calls) == 1
    assert calls[0][1] == ["spec", "tdd", "review"]
    app = Path(result["application"]["path"])
    assert (app / "frontend" / "src" / "App.tsx").is_file()
    assert (app / "backend" / "main.py").is_file()
    assert (app / "docker-compose.yml").is_file()
    assert "model-generated source is not executed" in result["note"]


def test_mimo_app_create_fails_closed_if_planning_step_fails(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return {
                "spec": {"content": "requirements"},
                "tdd": {"content": "[error] provider unavailable"},
                "review": {"content": "not reached"},
            }

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "must-not-exist", "spec": "A test app"})
    assert result["ok"] is False
    assert result["failed_steps"] == ["tdd"]
    assert not (home / "apps" / "must-not-exist").exists()


def test_mimo_app_create_rejects_output_path_escape(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            raise AssertionError("planner must not run for unsafe output path")

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {
        "name": "escape", "spec": "app", "output_dir": str(tmp_path / "outside")
    })
    assert result["ok"] is False
    assert "inside the sandbox apps directory" in result["error"]


def test_mimo_app_create_is_registered_as_a_real_tool():
    tool = next(item for item in HERMES_TOOL_REGISTRY if item["name"] == "mimo_app_create")
    assert tool["engine"] == "mimo"
    assert tool["fn"] is _mimo_app_create
