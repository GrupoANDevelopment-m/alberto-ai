"""MiMo application-generation integration regression tests."""
import json
from pathlib import Path
from types import SimpleNamespace

from alberto.engines.hermes_tools import _mimo_app_create, HERMES_TOOL_REGISTRY

def generated_manifest():
    return json.dumps({"files": {
        "frontend/src/App.tsx": "import { useState } from 'react'\nexport default function App() { const [n, setN] = useState(0); return <main><h1>Task manager</h1><button onClick={() => setN(n + 1)}>{n}</button></main> }",
        "backend/main.py": "from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI(title='Task manager')\n@app.get('/api/health')\ndef health():\n    return {'ok': True}\n",
    }})




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

        def invoke(self, prompt, **kwargs):
            assert "JSON object" in prompt
            assert kwargs["task"] == "code"
            return generated_manifest()

        def judge(self, candidate, *, criteria=None):
            assert "Task manager" in candidate
            return {"verdict": "pass", "score": 0.95, "reason": "reviewed"}

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
    assert "generated the application source" in result["note"].lower()
    assert result["application"]["generated_files"] == ["backend/main.py", "frontend/src/App.tsx"]
    assert "Task manager" in (app / "frontend" / "src" / "App.tsx").read_text()
    assert "FastAPI(title='Task manager')" in (app / "backend" / "main.py").read_text()


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

        def invoke(self, prompt, **kwargs):
            raise AssertionError("generation must not run after failed planning")

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("review must not run after failed planning")

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

        def invoke(self, prompt, **kwargs):
            raise AssertionError("generation must not run for unsafe output path")

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("review must not run for unsafe output path")

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

        def invoke(self, prompt, **kwargs):
            raise AssertionError("generation must not run without every planning stage")

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("review must not run without every planning stage")

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

        def invoke(self, prompt, **kwargs):
            raise AssertionError("generation must not run without every planning stage")

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("review must not run without every planning stage")

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "incomplete-plan", "spec": "an app"})
    assert result["ok"] is False
    assert "tdd" in result["failed_steps"]
    assert not (home / "apps" / "incomplete-plan").exists()


def test_mimo_app_create_rejects_non_allowlisted_generated_source_without_artifact(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return {
                "spec": {"content": "requirements", "verdict": {"verdict": "pass"}},
                "tdd": {"content": "tests", "verdict": {"verdict": "pass"}},
                "review": {"content": "review", "verdict": {"verdict": "pass"}},
            }

        def invoke(self, prompt, **kwargs):
            manifest = json.loads(generated_manifest())
            manifest["files"]["backend/main.py"] = (
                "import subprocess\nfrom fastapi import FastAPI\napp = FastAPI()\n"
            )
            return json.dumps(manifest)

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("static import gate must reject before model review")

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "unsafe-import", "spec": "A task manager"})
    assert result["ok"] is False
    assert "non-allowlisted import" in result["error"]
    assert not (home / "apps" / "unsafe-import").exists()


def test_mimo_app_create_rejects_invalid_generated_python_before_materializing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return {
                "spec": {"content": "requirements", "verdict": {"verdict": "pass"}},
                "tdd": {"content": "tests", "verdict": {"verdict": "pass"}},
                "review": {"content": "review", "verdict": {"verdict": "pass"}},
            }

        def invoke(self, prompt, **kwargs):
            manifest = json.loads(generated_manifest())
            manifest["files"]["backend/main.py"] = "from fastapi import FastAPI\napp = FastAPI(\n"
            return json.dumps(manifest)

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("syntax gate must reject before model review")

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "syntax-error", "spec": "A task manager"})
    assert result["ok"] is False
    assert "invalid Python syntax" in result["error"]
    assert not (home / "apps" / "syntax-error").exists()


def test_mimo_app_create_requires_generated_source_review_to_pass(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return {
                "spec": {"content": "requirements", "verdict": {"verdict": "pass"}},
                "tdd": {"content": "tests", "verdict": {"verdict": "pass"}},
                "review": {"content": "review", "verdict": {"verdict": "pass"}},
            }

        def invoke(self, prompt, **kwargs):
            return generated_manifest()

        def judge(self, candidate, *, criteria=None):
            return {"verdict": "fail", "score": 0.2, "reason": "unsafe or incomplete"}

    alberto = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    result = _mimo_app_create(alberto, {"name": "review-failed", "spec": "A task manager"})
    assert result["ok"] is False
    assert result["error"] == "MiMo generated-source review did not pass"
    assert not (home / "apps" / "review-failed").exists()


def test_mimo_app_create_requires_configured_sandbox(tmp_path):
    result = _mimo_app_create(SimpleNamespace(mimo=None), {"name": "no-sandbox", "spec": "an app"})
    assert result["ok"] is False
    assert "configured sandbox" in result["error"]


def test_mimo_app_create_refuses_host_materialization_for_docker_sandbox(tmp_path):
    home = tmp_path / "container-home"
    home.mkdir()
    calls = []

    class Mimo:
        def compose(self, spec, *, steps):
            calls.append("compose")
            raise AssertionError("planning must not run before the sandbox mode is supported")

    sandbox = SimpleNamespace(home=lambda: home, isolation_level="docker-container")
    result = _mimo_app_create(
        SimpleNamespace(mimo=Mimo(), sandbox=sandbox),
        {"name": "docker-app", "spec": "A small app"},
    )

    assert result["ok"] is False
    assert "Docker mode is refused" in result["error"]
    assert calls == []
    assert not (home / "apps").exists()



def _passing_plan():
    return {
        "spec": {"content": "requirements", "verdict": {"verdict": "pass"}},
        "tdd": {"content": "acceptance tests", "verdict": {"verdict": "pass"}},
        "review": {"content": "security review", "verdict": {"verdict": "pass"}},
    }


def test_mimo_app_create_rejects_invalid_request_shapes_before_planning(tmp_path):
    import pytest

    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, *args, **kwargs):
            raise AssertionError("invalid requests must be rejected before planning")

    agent = SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home))
    cases = [
        ({"name": "../escape", "spec": "valid spec"}, "slug"),
        ({"name": "missing-spec"}, "valid 'name'"),
        ({"name": "too-long-spec", "spec": "x" * 4001}, "at most 4000"),
        ({"name": "wrong-stack", "spec": "valid", "stack": "python"}, "unsupported stack"),
        ({"name": "empty-output", "spec": "valid", "output_dir": ""}, "non-empty path"),
        ({"name": "non-string-output", "spec": "valid", "output_dir": []}, "non-empty path"),
    ]
    for args, expected_error in cases:
        result = _mimo_app_create(agent, args)
        assert result["ok"] is False
        assert expected_error in result["error"]


def test_mimo_app_create_reports_generation_json_error_without_artifact(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return _passing_plan()

        def invoke(self, prompt, **kwargs):
            return "this is not JSON"

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("invalid JSON must be rejected before review")

    result = _mimo_app_create(
        SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home)),
        {"name": "bad-json", "spec": "a safe app"},
    )
    assert result["ok"] is False
    assert "valid JSON" in result["error"]
    assert not (home / "apps" / "bad-json").exists()


def test_mimo_app_create_rejects_dynamic_frontend_import(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return _passing_plan()

        def invoke(self, prompt, **kwargs):
            manifest = json.loads(generated_manifest())
            manifest["files"]["frontend/src/App.tsx"] = (
                "const x = import('untrusted-module'); export default function App() { return null; }"
            )
            return json.dumps(manifest)

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("dynamic import must be rejected before review")

    result = _mimo_app_create(
        SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home)),
        {"name": "dynamic-import", "spec": "a safe app"},
    )
    assert result["ok"] is False
    assert "dynamic import" in result["error"]
    assert not (home / "apps" / "dynamic-import").exists()


def test_mimo_app_create_rejects_host_file_access_in_generated_backend(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return _passing_plan()

        def invoke(self, prompt, **kwargs):
            manifest = json.loads(generated_manifest())
            manifest["files"]["backend/main.py"] = (
                "from fastapi import FastAPI\napp = FastAPI()\nopen('outside.txt', 'w')\n"
            )
            return json.dumps(manifest)

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("host file access must be rejected before review")

    result = _mimo_app_create(
        SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home)),
        {"name": "host-access", "spec": "a safe app"},
    )
    assert result["ok"] is False
    assert "prohibited dynamic-code or host-access" in result["error"]
    assert not (home / "apps" / "host-access").exists()


def test_mimo_app_create_rejects_backend_without_fastapi_app(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return _passing_plan()

        def invoke(self, prompt, **kwargs):
            manifest = json.loads(generated_manifest())
            manifest["files"]["backend/main.py"] = "def app():\n    return {'ok': True}\n"
            return json.dumps(manifest)

        def judge(self, candidate, *, criteria=None):
            raise AssertionError("missing FastAPI construction must be rejected before review")

    result = _mimo_app_create(
        SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home)),
        {"name": "no-fastapi", "spec": "a safe app"},
    )
    assert result["ok"] is False
    assert "must construct a FastAPI application" in result["error"]
    assert not (home / "apps" / "no-fastapi").exists()


def test_mimo_app_create_surfaces_planning_generation_and_review_failures(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    class PlanningFailure:
        def compose(self, spec, *, steps):
            raise RuntimeError("provider unavailable")

    result = _mimo_app_create(
        SimpleNamespace(mimo=PlanningFailure(), sandbox=SimpleNamespace(home=lambda: home)),
        {"name": "planning-failure", "spec": "a safe app"},
    )
    assert result["ok"] is False
    assert "planning failed" in result["error"]

    class GenerationFailure:
        def compose(self, spec, *, steps):
            return _passing_plan()

        def invoke(self, prompt, **kwargs):
            raise RuntimeError("provider unavailable")

    result = _mimo_app_create(
        SimpleNamespace(mimo=GenerationFailure(), sandbox=SimpleNamespace(home=lambda: home)),
        {"name": "generation-failure", "spec": "a safe app"},
    )
    assert result["ok"] is False
    assert "source generation failed" in result["error"]

    class ReviewFailure:
        def compose(self, spec, *, steps):
            return _passing_plan()

        def invoke(self, prompt, **kwargs):
            return generated_manifest()

        def judge(self, candidate, *, criteria=None):
            raise RuntimeError("review unavailable")

    result = _mimo_app_create(
        SimpleNamespace(mimo=ReviewFailure(), sandbox=SimpleNamespace(home=lambda: home)),
        {"name": "review-failure", "spec": "a safe app"},
    )
    assert result["ok"] is False
    assert "source review failed" in result["error"]


def test_mimo_generated_backend_serves_its_declared_health_contract(tmp_path):
    import importlib.util
    import sys
    from fastapi.testclient import TestClient

    home = tmp_path / "home"
    home.mkdir()

    class Mimo:
        def compose(self, spec, *, steps):
            return _passing_plan()

        def invoke(self, prompt, **kwargs):
            return generated_manifest()

        def judge(self, candidate, *, criteria=None):
            return {"verdict": "pass", "score": 0.95, "reason": "reviewed"}

    result = _mimo_app_create(
        SimpleNamespace(mimo=Mimo(), sandbox=SimpleNamespace(home=lambda: home)),
        {"name": "health-contract", "spec": "A task manager with a health endpoint"},
    )
    assert result["ok"] is True

    backend_file = Path(result["application"]["path"]) / "backend" / "main.py"
    spec = importlib.util.spec_from_file_location("generated_mimo_backend_contract", backend_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        with TestClient(module.app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            assert response.json() == {"ok": True}
    finally:
        sys.modules.pop(spec.name, None)
