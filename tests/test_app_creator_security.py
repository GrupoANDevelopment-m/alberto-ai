"""Security and regression tests for generated applications."""
import ast
import json
from pathlib import Path

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
    assert 'raise RuntimeError("injected")' not in backend_source


def test_create_scaffolds_expected_files_and_duplicate_is_non_destructive(tmp_path):
    creator = AppCreator(tmp_path / "apps")
    result = creator.create("demo_app-1", "A test application")
    assert result["ok"] is True
    root = Path(result["path"])
    expected = [
        "frontend/package.json", "frontend/index.html", "frontend/src/App.tsx",
        "backend/main.py", "backend/requirements.txt", "backend/pyproject.toml",
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
