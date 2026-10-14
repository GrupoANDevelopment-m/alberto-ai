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
                "spec": {"content": "Requirements and architecture", "verdict": {"verdict": "pass"}},
                "tdd": {"content": "Acceptance test plan", "verdict": {"verdict": "pass"}},
                "review": {"content": "Security review", "verdict": {"verdict": "pass"}},
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
    assert "model-generated source is not executed" in result["note"].lower()


def test_mimo_app_create_fails_closed_if_planning_step_fails(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return {
                "spec": {"content": "requirements", "verdict": {"verdict": "pass"}},
                "tdd": {"content": "[error] provider unavailable", "verdict": {"verdict": "fail"}},
                "review": {"content": "not reached", "verdict": {"verdict": "fail"}},
            }

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "must-not-exist", "spec": "A test app"})
    assert result["ok"] is False
    assert result["failed_steps"] == ["tdd", "review"]
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



def test_mimo_app_create_rejects_missing_required_planning_stage(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return {
                "spec": {"content": "requirements", "verdict": {"verdict": "pass"}},
                "review": {"content": "security review", "verdict": {"verdict": "pass"}},
            }

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "partial-plan", "spec": "A test app"})
    assert result["ok"] is False
    assert result["failed_steps"] == ["tdd"]
    assert not (home / "apps" / "partial-plan").exists()


def test_mimo_app_create_rejects_symlinked_output_escape(tmp_path):
    home = tmp_path / "home"
    apps = home / "apps"
    apps.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (apps / "escape-link").symlink_to(outside, target_is_directory=True)

    class Mimo:
        def compose(self, spec, *, steps):
            raise AssertionError("planner must not run for a symlinked escape")

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {
        "name": "escape", "spec": "app", "output_dir": "escape-link"
    })
    assert result["ok"] is False
    assert "inside the sandbox apps directory" in result["error"]
    assert list(outside.iterdir()) == []



def test_mimo_app_create_rejects_symlinked_apps_root(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (home / "apps").symlink_to(external, target_is_directory=True)

    class Mimo:
        def compose(self, spec, *, steps):
            raise AssertionError("planning must not run when apps root is symlinked")

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "escape", "spec": "an app"})
    assert result["ok"] is False
    assert "must not be a symlink" in result["error"]
    assert not (external / "escape").exists()


def test_mimo_app_create_rejects_plan_missing_required_stage(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return {
                "spec": {"content": "requirements", "verdict": {"verdict": "pass"}},
                "review": {"content": "reviewed", "verdict": {"verdict": "pass"}},
            }

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "incomplete-plan", "spec": "an app"})
    assert result["ok"] is False
    assert "tdd" in result["failed_steps"]
    assert not (home / "apps" / "incomplete-plan").exists()
