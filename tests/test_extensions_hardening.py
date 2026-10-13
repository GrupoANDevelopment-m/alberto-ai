"""Security regressions for extension installation path handling."""
from pathlib import Path

import pytest

from alberto.runtime.extensions import ExtensionInstaller


@pytest.fixture
def installer(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    instance = ExtensionInstaller()
    instance.local_skills = tmp_path / "project-skills"
    instance.local_skills.mkdir()
    return instance


@pytest.mark.parametrize("name", ["../escape", "..", ".", "a/b", "a\\b", ""])
def test_install_rejects_path_traversal_names_before_writing(installer, name):
    with pytest.raises(ValueError, match="extension name"):
        installer.install(name, source="skill:example")


def test_install_rejects_unknown_extension_type(installer):
    with pytest.raises(ValueError, match="unsupported extension type"):
        installer.install("safe-name", source="skill:example", ext_type="../outside")


def test_create_skill_rejects_traversal_in_name_and_category(installer, tmp_path):
    with pytest.raises(ValueError, match="skill name"):
        installer.create_skill("../outside", description="x", content="x")
    with pytest.raises(ValueError, match="skill category"):
        installer.create_skill("safe", description="x", content="x", category="../outside")
    assert not (tmp_path / "outside").exists()


def test_create_skill_writes_only_inside_skills_root(installer):
    path = installer.create_skill(
        "reviewer", description="Reviews code", content="Inspect changed files.",
        category="testing",
    )
    assert path == installer.local_skills / "testing" / "reviewer" / "SKILL.md"
    assert path.is_file()
    assert "Inspect changed files." in path.read_text()


def test_list_enable_disable_and_uninstall_lifecycle(installer, tmp_path):
    source = tmp_path / "source-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Safe skill")
    installed = installer.install("sample", source=str(source))
    assert installed.name == "sample"
    assert installer.list("skill")[0].name == "sample"
    assert installer.disable("sample") is True
    assert installer.list()[0].enabled is False
    assert installer.enable("sample") is True
    assert installer.uninstall("sample") is True
    assert installer.uninstall("sample") is False
    assert installer.list() == []
