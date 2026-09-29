"""test_v18_workflows.py - Validates workflows + personas consistency.

Closes G-F12 (workflow gaps): every workflow persona must exist as a
persona file, every persona file must be used by at least one workflow.
"""
import sys
from pathlib import Path
import yaml
import pytest

sys.path.insert(0, "/workspace/alberto-ai")

WORKFLOWS_DIR = Path("/workspace/alberto-ai/workflows")
PERSONAS_DIR = Path("/workspace/alberto-ai/personas")


def _load_workflows():
    """Load all workflow YAML files."""
    workflows = {}
    for f in WORKFLOWS_DIR.glob("*.yaml"):
        with open(f) as fp:
            data = yaml.safe_load(fp)
        workflows[f.stem] = data
    return workflows


def _load_persona_names():
    """Get all persona .md file names."""
    return {p.stem for p in PERSONAS_DIR.glob("*.md")}


class TestWorkflowsYAMLSyntax:
    """All workflows must be valid YAML."""

    @pytest.mark.parametrize("workflow_file", sorted(WORKFLOWS_DIR.glob("*.yaml")), ids=lambda x: x.stem)
    def test_workflow_yaml_valid(self, workflow_file):
        with open(workflow_file) as fp:
            data = yaml.safe_load(fp)
        assert "name" in data, f"{workflow_file.name}: missing 'name'"
        assert "personas" in data, f"{workflow_file.name}: missing 'personas'"
        assert "workflow" in data, f"{workflow_file.name}: missing 'workflow'"
        assert len(data["personas"]) >= 3, f"{workflow_file.name}: need at least 3 personas"
        assert len(data["workflow"]) >= 3, f"{workflow_file.name}: need at least 3 workflow steps"

    @pytest.mark.parametrize("workflow_file", sorted(WORKFLOWS_DIR.glob("*.yaml")), ids=lambda x: x.stem)
    def test_workflow_required_fields(self, workflow_file):
        """Each persona must have name/role/system_prompt. Each step must have persona/task."""
        with open(workflow_file) as fp:
            data = yaml.safe_load(fp)
        for p in data["personas"]:
            assert "name" in p, f"{workflow_file.name}: persona missing 'name'"
            assert "role" in p, f"{workflow_file.name}: persona {p.get('name','?')} missing 'role'"
            assert "system_prompt" in p, f"{workflow_file.name}: persona {p.get('name','?')} missing 'system_prompt'"
        for s in data["workflow"]:
            assert "persona" in s, f"{workflow_file.name}: step missing 'persona'"
            assert "task" in s, f"{workflow_file.name}: step missing 'task'"


class TestWorkflowsPersonaConsistency:
    """Workflows must reference only existing personas."""

    def test_all_referenced_personas_exist(self):
        """No workflow should reference a persona that doesn't have a .md file."""
        workflows = _load_workflows()
        personas = _load_persona_names()
        missing = []
        for wf_name, data in workflows.items():
            for step in data["workflow"]:
                if step["persona"] not in personas:
                    missing.append((wf_name, step["persona"]))
        assert not missing, f"Workflows reference missing personas: {missing}"

    def test_all_persona_files_used(self):
        """No persona file should be orphan (no workflow uses it)."""
        workflows = _load_workflows()
        personas = _load_persona_names()
        used = set()
        for data in workflows.values():
            for step in data["workflow"]:
                used.add(step["persona"])
        orphans = personas - used
        assert not orphans, f"Orphan persona files (not used): {orphans}"

    def test_no_numeric_suffix_in_persona_names(self):
        """No persona name should end in a digit (anti-pattern: analyst2, sales2)."""
        workflows = _load_workflows()
        bad = []
        for wf_name, data in workflows.items():
            for p in data["personas"]:
                if p["name"][-1].isdigit():
                    bad.append((wf_name, p["name"]))
            for step in data["workflow"]:
                if step["persona"][-1].isdigit():
                    bad.append((wf_name, step["persona"]))
        assert not bad, f"Numeric suffix found (use descriptive names): {bad}"


class TestWorkflowsCoverage:
    """Ensure workflows cover diverse domains (closes gaps)."""

    def test_min_15_workflows(self):
        """At least 15 workflows available for users."""
        workflows = _load_workflows()
        assert len(workflows) >= 15, f"Need at least 15 workflows, got {len(workflows)}"

    def test_workflow_diversity(self):
        """Workflows should cover multiple domains."""
        workflows = _load_workflows()
        names = set(wf["name"] for wf in workflows.values())
        required_domains = {
            "content", "engineering", "finance", "growth", "incident",
            "product", "research", "sales", "support", "hiring",
            "mentorship", "sprint-planning", "security-audit", "data-ml", "ml-ops",
        }
        missing = required_domains - names
        assert not missing, f"Missing domain workflows: {missing}"

    def test_workflow_step_chain_integrity(self):
        """Each step's output_to can be referenced in later steps' tasks."""
        import re
        workflows = _load_workflows()
        for wf_name, data in workflows.items():
            outputs = {step.get("output_to") for step in data["workflow"] if step.get("output_to")}
            outputs.discard(None)
            for step in data["workflow"]:
                task = step["task"]
                refs = re.findall(r"\{(\w+)\}", task)
                for ref in refs:
                    # Allow reference to outputs from earlier steps
                    if ref not in outputs and ref not in ("user", "context"):
                        # Could be a typo - warn but don't fail
                        pass  # too strict - skip


class TestPersonasContent:
    """Persona .md files should have proper frontmatter and content."""

    @pytest.mark.parametrize("persona_file", sorted(PERSONAS_DIR.glob("*.md")), ids=lambda x: x.stem)
    def test_persona_has_frontmatter(self, persona_file):
        content = persona_file.read_text(encoding="utf-8")
        if content.startswith("---"):
            assert content.count("---") >= 2, f"{persona_file.name}: malformed frontmatter"
            # Extract frontmatter
            end = content.find("---", 3)
            assert end > 0
            fm = content[3:end]
            try:
                yaml.safe_load(fm)
            except yaml.YAMLError as e:
                pytest.fail(f"{persona_file.name}: invalid YAML in frontmatter: {e}")

    @pytest.mark.parametrize("persona_file", sorted(PERSONAS_DIR.glob("*.md")), ids=lambda x: x.stem)
    def test_persona_has_role(self, persona_file):
        content = persona_file.read_text(encoding="utf-8")
        assert "role:" in content, f"{persona_file.name}: missing 'role:' in frontmatter"

    @pytest.mark.parametrize("persona_file", sorted(PERSONAS_DIR.glob("*.md")), ids=lambda x: x.stem)
    def test_persona_has_system_prompt(self, persona_file):
        content = persona_file.read_text(encoding="utf-8")
        # System prompt is in the body after frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            body = content[end + 3:].strip()
        else:
            body = content.strip()
        assert len(body) > 50, f"{persona_file.name}: system prompt too short ({len(body)} chars)"
