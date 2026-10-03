"""test_v183_crewai.py - Tests for the real CrewAI runtime (replaces AIOX).

CrewAI 1.15+ is a real production multi-agent framework that we use
to replace the AIOX stub. These tests verify:
1. CrewAI is available
2. Status reporting works
3. Squad execution works end-to-end with real LLM
4. Error handling is real (not stub)
"""
import os
import sys
import pytest

# Mark heavy integration tests as slow (require real LLM, may rate-limit)
pytestmark_slow = pytest.mark.slow
sys.path.insert(0, "/workspace/alberto-ai")


class TestCrewAIIntegration:
    """Verify real CrewAI integration (replaces AIOX)."""

    def test_crewai_available(self):
        """CrewAI 1.15+ must be installed."""
        from alberto.runtime.crewai_runtime import is_crewai_available
        assert is_crewai_available() is True

    def test_status_reports_real_crewai(self):
        """Status should report real CrewAI version, not stub."""
        from alberto.runtime.crewai_runtime import get_crewai_status
        s = get_crewai_status()
        assert s["crewai_available"] is True
        assert s["version"] is not None
        # Major version 1.x means real CrewAI
        assert s["version"].startswith("1.")
        # Should explicitly say it replaces AIOX
        assert "aiox" in s["replaces"].lower()


class TestCrewAISquadExecution:
    """End-to-end tests: real CrewAI squad execution with real LLM."""

    @pytest.fixture(autouse=True)
    def require_keys(self):
        if not os.environ.get("NVIDIA_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("Need NVIDIA_API_KEY or OPENAI_API_KEY")

    def test_engineering_squad_runs(self):
        """engineering squad: 5 personas execute sequentially."""
        from alberto.runtime.crewai_runtime import run_crew_squad
        r = run_crew_squad(
            squad_name="engineering",
            workflow_yaml_path="/workspace/alberto-ai/workflows/engineering.yaml",
            personas_dir="/workspace/alberto-ai/personas",
            llm_model="openai/google/diffusiongemma-26b-a4b-it",
            llm_base_url="https://integrate.api.nvidia.com/v1",
            user_prompt="Build a click counter in JS. Brief answer.",
        )
        assert r.get("ok") is True
        assert r.get("engine") == "crewai"
        assert "outputs" in r
        assert "final" in r["outputs"]
        assert len(r["outputs"]["final"]) > 0

    def test_smoke_squad_fast(self):
        """Fast smoke test using 2-step workflow (rate-limit friendly)."""
        from alberto.runtime.crewai_runtime import run_crew_squad
        r = run_crew_squad(
            squad_name="smoke",
            workflow_yaml_path="/workspace/alberto-ai/workflows/smoke/minimal.yaml",
            personas_dir="/workspace/alberto-ai/personas",
            llm_model="openai/google/diffusiongemma-26b-a4b-it",
            llm_base_url="https://integrate.api.nvidia.com/v1",
            user_prompt="Count clicks",
        )
        assert r.get("ok") is True
        assert r.get("engine") == "crewai"
        assert len(r["outputs"]["final"]) > 0

    @pytest.mark.slow
    def test_content_squad_runs(self):
        """content squad: 5 personas (researcher, content, writer, editor, tech_writer)."""
        from alberto.runtime.crewai_runtime import run_crew_squad
        r = run_crew_squad(
            squad_name="content",
            workflow_yaml_path="/workspace/alberto-ai/workflows/content.yaml",
            personas_dir="/workspace/alberto-ai/personas",
            llm_model="openai/google/diffusiongemma-26b-a4b-it",
            llm_base_url="https://integrate.api.nvidia.com/v1",
            user_prompt="Write about Angola. Very short.",
        )
        assert r.get("ok") is True
        assert r.get("engine") == "crewai"
        assert len(r["outputs"]["final"]) > 0

    @pytest.mark.slow
    def test_hiring_squad_runs(self):
        """hiring squad (6 personas)."""
        from alberto.runtime.crewai_runtime import run_crew_squad
        r = run_crew_squad(
            squad_name="hiring",
            workflow_yaml_path="/workspace/alberto-ai/workflows/hiring.yaml",
            personas_dir="/workspace/alberto-ai/personas",
            llm_model="openai/google/diffusiongemma-26b-a4b-it",
            llm_base_url="https://integrate.api.nvidia.com/v1",
            user_prompt="Hire a senior Python dev. Brief.",
        )
        assert r.get("ok") is True
        assert r.get("engine") == "crewai"

    @pytest.mark.slow
    def test_security_audit_squad_runs(self):
        """security-audit squad (6 personas)."""
        from alberto.runtime.crewai_runtime import run_crew_squad
        r = run_crew_squad(
            squad_name="security-audit",
            workflow_yaml_path="/workspace/alberto-ai/workflows/security-audit.yaml",
            personas_dir="/workspace/alberto-ai/personas",
            llm_model="openai/google/diffusiongemma-26b-a4b-it",
            llm_base_url="https://integrate.api.nvidia.com/v1",
            user_prompt="Audit a web app. Brief.",
        )
        assert r.get("ok") is True
        assert r.get("engine") == "crewai"


class TestCrewAIErrorHandling:
    """Verify error handling is real, not stub."""

    def test_missing_workflow_file(self):
        """Should return real error for missing file."""
        from alberto.runtime.crewai_runtime import run_crew_squad
        r = run_crew_squad(
            squad_name="nonexistent",
            workflow_yaml_path="/tmp/does_not_exist.yaml",
            personas_dir="/workspace/alberto-ai/personas",
        )
        assert r.get("ok") is False
        assert "error" in r

    def test_missing_persona_file(self):
        """Should return real error for missing persona."""
        import tempfile
        from alberto.runtime.crewai_runtime import run_crew_squad
        # Create a workflow that references a non-existent persona
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
name: test
personas:
  - name: nonexistent_persona
    role: Test
workflow:
  - persona: nonexistent_persona
    task: do something
    output_to: result
""")
            wf_path = f.name
        try:
            r = run_crew_squad(
                squad_name="test",
                workflow_yaml_path=wf_path,
                personas_dir="/workspace/alberto-ai/personas",
            )
            assert r.get("ok") is False
            assert "missing" in r.get("error", "").lower() or "persona" in r.get("error", "").lower()
        finally:
            os.unlink(wf_path)

    def test_no_api_key(self):
        """Should return real error when no API key."""
        from alberto.runtime import crewai_runtime
        # Save and clear env
        saved = {}
        for k in ("NVIDIA_API_KEY", "OPENAI_API_KEY"):
            if k in os.environ:
                saved[k] = os.environ.pop(k)
        try:
            r = crewai_runtime.run_crew_squad(
                squad_name="engineering",
                workflow_yaml_path="/workspace/alberto-ai/workflows/engineering.yaml",
                personas_dir="/workspace/alberto-ai/personas",
            )
            assert r.get("ok") is False
            assert "api key" in r.get("error", "").lower() or "no_api" in r.get("error", "").lower()
        finally:
            for k, v in saved.items():
                os.environ[k] = v
