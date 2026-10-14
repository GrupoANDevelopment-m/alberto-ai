"""Security and regression tests for generated applications."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

from alberto.runtime.app_creator import AppCreator


def test_rejects_path_traversal_and_source_injection_names(tmp_path):
    creator = AppCreator(tmp_path / "apps")
    for name in ("../outside", "/tmp/escape", "x/y", "", ".", "a b", "a;import os"):
        result = creator.create(name, "safe description")
        assert result["ok"] is False
    assert not (tmp_path / "outside").exists()
    assert list((tmp_path / "apps").iterdir()) == []


def test_rejects_non_string_or_oversized_descriptions(tmp_path):
    creator = AppCreator(tmp_path / "apps")
    assert creator.create("valid-app", None)["ok"] is False
    assert creator.create("valid-app", "x" * 4001)["ok"] is False
    assert list((tmp_path / "apps").iterdir()) == []


def test_generated_sources_keep_untrusted_description_as_data(tmp_path):
    description = 'quote " ; braces {x}; </p>\\nraise RuntimeError("injected")'
    result = AppCreator(tmp_path / "apps").create("safe-app", description)
    assert result["ok"] is True
    root = Path(result["path"])
    backend_source = (root / "backend" / "main.py").read_text()
    ast.parse(backend_source)
    assert f"description={json.dumps(description)}" in backend_source
    assert f'"description": {json.dumps(description)}' in backend_source
    frontend_source = (root / "frontend" / "src" / "App.tsx").read_text()
    assert "{" + json.dumps(description) + "}" in frontend_source
    assert not any(isinstance(node, ast.Raise) for node in ast.walk(ast.parse(backend_source)))


def test_create_scaffolds_expected_files_and_duplicate_is_non_destructive(tmp_path):
    creator = AppCreator(tmp_path / "apps")
    result = creator.create("demo_app-1", "A test application")
    assert result["ok"] is True
    root = Path(result["path"])
    expected = [
        "frontend/package.json", "frontend/index.html", "frontend/src/App.tsx",
        "backend/main.py", "backend/requirements.txt", "backend/pyproject.toml", "backend/Dockerfile", "frontend/Dockerfile",
        "docker-compose.yml", "README.md",
    ]
    assert all((root / name).is_file() for name in expected)
    before = (root / "backend" / "main.py").read_text()
    duplicate = creator.create("demo_app-1", "overwrite attempt")
    assert duplicate["ok"] is False
    assert (root / "backend" / "main.py").read_text() == before


def test_output_dir_override_is_respected(tmp_path):
    creator = AppCreator(tmp_path / "initial")
    target = tmp_path / "override"
    result = creator.create("project", "desc", output_dir=target)
    assert result["ok"] is True
    assert Path(result["path"]).parent == target


def test_generated_services_bind_to_loopback_by_default(tmp_path):
    creator = AppCreator(tmp_path / "apps")
    result = creator.create("local-only", "Local development")
    root = Path(result["path"])
    package = json.loads((root / "frontend" / "package.json").read_text())
    compose = (root / "docker-compose.yml").read_text()
    assert "--host 127.0.0.1" in package["scripts"]["dev"]
    assert "127.0.0.1:3000:3000" in compose
    assert "127.0.0.1:8000:8000" in compose
    backend = (root / "backend" / "main.py").read_text()
    assert 'allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"]' in backend
    assert 'allow_origins=["*"]' not in backend


def test_rejects_unsupported_stack_without_creating_files(tmp_path):
    creator = AppCreator(tmp_path / "apps")
    result = creator.create("valid-app", "description", stack="unknown-stack")
    assert result["ok"] is False
    assert "unsupported stack" in result["error"]
    assert list((tmp_path / "apps").iterdir()) == []

def test_run_attempts_both_services_and_reports_pids(tmp_path, monkeypatch):
    creator = AppCreator(tmp_path / "apps")
    created = creator.create("runnable", "test")
    calls = []

    class Process:
        pid = 1234

        def poll(self):
            return None

    def fake_run(args, **kwargs):
        calls.append(("run", args, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    def fake_popen(args, **kwargs):
        calls.append(("popen", args, kwargs))
        return Process()

    monkeypatch.setattr("alberto.runtime.app_creator.shutil.which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.run", fake_run)
    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.Popen", fake_popen)
    monkeypatch.setattr("alberto.runtime.app_creator.time.sleep", lambda *_: None)

    result = creator.run(Path(created["path"]))
    assert result["ok"] is True
    assert result["backend_started"] is True
    assert result["frontend_started"] is True
    assert result["backend_pid"] == 1234
    assert result["frontend_pid"] == 1234
    assert sum(1 for kind, *_ in calls if kind == "popen") == 2
    assert any(kind == "run" and args[0] == "npm" for kind, args, _ in calls)


def test_run_cleans_up_backend_when_npm_is_missing(tmp_path, monkeypatch):
    creator = AppCreator(tmp_path / "apps")
    created = creator.create("no-npm", "test")

    class Process:
        pid = 55

        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            raise AssertionError("kill should not be needed")

    processes = []
    def fake_popen(*args, **kwargs):
        proc = Process()
        processes.append(proc)
        return proc

    monkeypatch.setattr("alberto.runtime.app_creator.shutil.which", lambda _name: None)
    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.run", lambda *a, **k: SimpleNamespace(returncode=0, stderr=""))
    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.Popen", fake_popen)
    monkeypatch.setattr("alberto.runtime.app_creator.time.sleep", lambda *_: None)

    result = creator.run(Path(created["path"]))
    assert result["backend_started"] is False
    assert "backend_pid" not in result
    assert processes[0].terminated is True
    assert result["frontend_started"] is False
    assert result["ok"] is False
    assert result["frontend_error"] == "npm not available"



def test_run_reports_backend_install_exception_and_missing_npm(tmp_path, monkeypatch):
    creator = AppCreator(tmp_path / "apps")
    created = creator.create("backend-install-error", "test")

    def fake_run(*args, **kwargs):
        raise TimeoutError("backend dependency installation timed out")

    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.run", fake_run)
    monkeypatch.setattr("alberto.runtime.app_creator.shutil.which", lambda _name: None)

    result = creator.run(Path(created["path"]))
    assert result["ok"] is False
    assert result["backend_started"] is False
    assert "timed out" in result["backend_error"]
    assert result["frontend_started"] is False
    assert result["frontend_error"] == "npm not available"


def test_run_reports_backend_process_exit_and_frontend_install_failure(tmp_path, monkeypatch):
    creator = AppCreator(tmp_path / "apps")
    created = creator.create("startup-errors", "test")

    class ExitedProcess:
        pid = 101

        def poll(self):
            return 1

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["-m", "pip"]:
            return SimpleNamespace(returncode=0, stderr="")
        return SimpleNamespace(returncode=1, stderr="npm registry unavailable")

    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.run", fake_run)
    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.Popen", lambda *a, **k: ExitedProcess())
    monkeypatch.setattr("alberto.runtime.app_creator.shutil.which", lambda _name: "/usr/bin/npm")
    monkeypatch.setattr("alberto.runtime.app_creator.time.sleep", lambda *_: None)

    result = creator.run(Path(created["path"]))
    assert result["ok"] is False
    assert result["backend_started"] is False
    assert result["backend_error"] == "backend process exited during startup"
    assert result["frontend_started"] is False
    assert "npm registry unavailable" in result["frontend_error"]
    assert len(calls) == 2


def test_run_cleans_up_backend_when_frontend_install_fails(tmp_path, monkeypatch):
    creator = AppCreator(tmp_path / "apps")
    created = creator.create("frontend-install-error", "test")
    processes = []

    class RunningProcess:
        pid = 202

        def __init__(self):
            self.terminated = False
            self.killed = False
            self.waited = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            return 0

        def kill(self):
            self.killed = True

    def fake_run(args, **kwargs):
        if args[1:3] == ["-m", "pip"]:
            return SimpleNamespace(returncode=0, stderr="")
        return SimpleNamespace(returncode=1, stderr="npm install failed")

    def fake_popen(*args, **kwargs):
        proc = RunningProcess()
        processes.append(proc)
        assert kwargs["stdout"] is __import__("subprocess").DEVNULL
        assert kwargs["stderr"] is __import__("subprocess").DEVNULL
        return proc

    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.run", fake_run)
    monkeypatch.setattr("alberto.runtime.app_creator.subprocess.Popen", fake_popen)
    monkeypatch.setattr("alberto.runtime.app_creator.shutil.which", lambda _name: "/usr/bin/npm")
    monkeypatch.setattr("alberto.runtime.app_creator.time.sleep", lambda *_: None)

    result = creator.run(Path(created["path"]))
    assert result["backend_started"] is False
    assert "backend_pid" not in result
    assert result["backend_cleanup"] == "terminated because the full app did not start"
    assert processes[0].terminated is True
    assert processes[0].waited is True
    assert result["frontend_started"] is False
    assert "npm install failed" in result["frontend_error"]
    assert result["ok"] is False
