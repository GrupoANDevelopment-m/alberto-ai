"""Security regressions for generated skill names, metadata, and paths."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alberto.runtime.learner import Learner


def make_learner(tmp_path):
    sandbox_home = tmp_path / "sandbox"
    sandbox_home.mkdir()
    learner = Learner(SimpleNamespace(home=lambda: sandbox_home), mimo=None)
    learner.user_skills_dir = tmp_path / "skills" / "user"
    learner.user_skills_dir.mkdir(parents=True)
    return learner


@pytest.mark.parametrize("name", [
    "../escape", "../../tmp/escape", "/tmp/escape", "has space", "UPPER", ".", "",
    "a" * 65, "name\\\\nested", "name/child",
])
def test_create_skill_rejects_invalid_or_traversal_names(tmp_path, name):
    learner = make_learner(tmp_path)
    with pytest.raises(ValueError, match="invalid skill name"):
        learner.create_skill(name, description="desc", content="body")
    assert not (tmp_path / "escape" / "SKILL.md").exists()


def test_create_skill_quotes_frontmatter_scalars_and_keeps_metadata_structure(tmp_path):
    learner = make_learner(tmp_path)
    description = 'safe description\\nmetadata:\\n  attacker: "injected"'
    category = 'user\\n    injected: true'
    path = learner.create_skill(
        "valid_skill", description=description, content="body",
        category=category, tags=["normal", 'tag, with punctuation'], author='author: injected',
    )
    import yaml
    text = path.read_text(encoding="utf-8")
    frontmatter = text.split("---\\n", 2)[1]
    parsed = yaml.safe_load(frontmatter)
    assert parsed["description"] == description
    assert parsed["metadata"]["alberto"]["category"] == category
    assert parsed["metadata"]["alberto"]["tags"] == ["normal", "tag, with punctuation"]
    assert parsed["author"] == "author: injected"
    assert "injected" not in parsed["metadata"]["alberto"]


def test_create_skill_rejects_oversized_or_malformed_code_blocks(tmp_path):
    learner = make_learner(tmp_path)
    with pytest.raises(ValueError, match="code block"):
        learner.create_skill("valid_skill", description="desc", content="body",
                             code_blocks=[{"lang": "bash"}])
    with pytest.raises(ValueError, match="combined code"):
        learner.create_skill("valid_skill", description="desc", content="body",
                             code_blocks=[{"lang": "bash", "code": "x" * 100001}])


def test_create_skill_rejects_symlinked_target(tmp_path):
    learner = make_learner(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = learner.user_skills_dir / "linked_skill"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ValueError, match="symlink"):
        learner.create_skill("linked_skill", description="desc", content="body")
    assert not (outside / "SKILL.md").exists()


def test_evolve_skill_refuses_skill_outside_user_directory(tmp_path, monkeypatch):
    learner = make_learner(tmp_path)
    external = tmp_path / "other" / "SKILL.md"
    external.parent.mkdir()
    external.write_text("---\\nname: external\\nversion: 0.1.0\\n---\\nbody", encoding="utf-8")
    import alberto.runtime.skill_engine as engine
    monkeypatch.setattr(engine, "find_skill", lambda name: external)
    with pytest.raises(ValueError, match="only user-created skills"):
        learner.evolve_skill("external", improvements="unsafe")
    assert "Evolution" not in external.read_text(encoding="utf-8")


def test_grep_stops_at_total_scan_budget(tmp_path, monkeypatch):
    from alberto.runtime import function_caller as caller
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    for index in range(5):
        (sandbox / f"{index}.txt").write_text("unmatched text\n" * 10, encoding="utf-8")
    monkeypatch.setattr(caller, "GREP_MAX_TOTAL_BYTES", 25)
    monkeypatch.setattr(caller, "GREP_MAX_FILES", 10)
    monkeypatch.setattr(caller, "GREP_MAX_FILE_BYTES", 1024)
    alberto = SimpleNamespace(sandbox=SimpleNamespace(home=lambda: sandbox))
    output, is_error = caller.tool_grep(alberto, {"pattern": "not-present", "path": str(sandbox)})
    assert is_error is False
    assert "search truncated: resource limit reached" in output
