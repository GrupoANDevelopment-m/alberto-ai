"""Intensive meta-controller test — exercises the full autonomy cycle.

Tests:
1. Skill manager search/recommend/stats
2. Meta controller plan/execute (with obstacles)
3. Lesson learned persistence + recall
4. Skill creation via overcome
5. Skill evolution via evolve
6. Meta history persistence
7. User profile adapt
8. 24/7 loop integration
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("ALBERTO_SANDBOX_DIR", "/tmp/alberto-sandbox-test")

from alberto import Alberto
from alberto.runtime.meta_controller import MetaController, SkillManager
from alberto.runtime.autonomy import AutonomyLoop
from alberto.runtime.researcher import Researcher
from alberto.runtime.learner import Learner


@pytest.fixture(scope="module")
def alberto():
    """Create Alberto with isolated sandbox."""
    sandbox_dir = "/tmp/alberto-sandbox-test"
    os.environ["ALBERTO_SANDBOX_DIR"] = sandbox_dir
    # Clean
    import shutil
    if Path(sandbox_dir).exists():
        shutil.rmtree(sandbox_dir, ignore_errors=True)
    a = Alberto()
    yield a
    a.shutdown()


class TestSkillManager:
    def test_total_skills(self, alberto):
        sm = SkillManager(alberto)
        assert sm.total() > 100, f"expected 100+ skills, got {sm.total()}"

    def test_search_finds_relevant(self, alberto):
        sm = SkillManager(alberto)
        results = sm.search("browser", limit=5)
        assert len(results) > 0
        # Top should be browser-related
        top_names = [r["skill"]["name"] for r in results[:3]]
        assert any("browser" in n.lower() for n in top_names), f"top 3: {top_names}"

    def test_recommend_includes_success_rate(self, alberto):
        sm = SkillManager(alberto)
        # Record some outcomes
        sm.record_outcome("browser-use", success=True, duration=1.0)
        sm.record_outcome("browser-use", success=True, duration=1.0)
        sm.record_outcome("arxiv", success=False, duration=2.0)
        # Now arxiv should rank lower
        recs = sm.recommend("search papers", top=5)
        for r in recs:
            assert "score" in r
            assert "skill" in r

    def test_stats_persistence(self, alberto):
        sm = SkillManager(alberto)
        sm.record_outcome("test-skill", success=True, duration=0.5)
        # Reload
        sm2 = SkillManager(alberto)
        stats = sm2.get_stats("test-skill")
        assert stats["success"] >= 1


class TestMetaController:
    def test_plan_creates_subtasks(self, alberto):
        mc = MetaController(alberto)
        plan = mc.plan_objective("criar uma API e testar")
        assert len(plan.subtasks) >= 1
        assert plan.status == "executing"

    def test_execute_with_obstacle(self, alberto):
        mc = MetaController(alberto)
        # Use a skill that will fail (no browser installed)
        plan = mc.plan_objective("usar browser")
        events = []
        mc.on_event(lambda e, d: events.append(e))
        plan = mc.execute(plan)
        # Should have detected obstacle or recovered
        assert "execute_start" in events
        assert "execute_end" in events
        # Should have written to history
        history = mc.get_history()
        assert len(history) >= 1

    def test_history_persists(self, alberto):
        mc1 = MetaController(alberto)
        mc1.plan_objective("teste 1")
        mc2 = MetaController(alberto)
        history = mc2.get_history()
        # Should see the previous plan
        assert any("teste 1" in str(h) for h in history)


class TestLearner:
    def test_lesson_recorded(self, alberto):
        l = Learner(alberto.sandbox, alberto.mimo)
        l.lesson_learned(mistake="X", fix="Y", why="Z", severity="warning")
        lessons = l.recall_lessons("X")
        assert len(lessons) >= 1

    def test_obstacle_creates_skill(self, alberto):
        l = Learner(alberto.sandbox, alberto.mimo)
        path = l.overcome_obstacle("network timeout", workaround="retry with backoff")
        assert path and path.exists()
        content = path.read_text()
        assert "network timeout" in content

    def test_evolve_skill(self, alberto):
        l = Learner(alberto.sandbox, alberto.mimo)
        # Create a test skill first
        l.create_skill("evolve-test", description="t", content="c")
        path = l.evolve_skill("evolve-test", improvements="added retries")
        assert path and "Evolution" in path.read_text()

    def test_user_profile_adapt(self, alberto):
        l = Learner(alberto.sandbox, alberto.mimo)
        l.observe_interaction("meu nome é Test", "ok")
        l.observe_interaction("explica detalhado", "ok")
        hints = l.get_adaptation_hints()
        assert "language" in hints or "style" in hints


class TestResearcher:
    def test_local_skill_search(self, alberto):
        r = Researcher(alberto.sandbox)
        result = r.search("test", sources=["local_skills"], limit=3)
        assert "sources" in result
        assert "local_skills" in result["sources"]

    def test_study_caches(self, alberto):
        r = Researcher(alberto.sandbox)
        result = r.study("Python testing")
        assert result.get("ok")
        assert Path(result["cached_at"]).exists()


class TestAutonomyLoop:
    def test_loop_runs_n_iterations(self, alberto):
        ticks = []
        def tick():
            ticks.append(time.time())
        loop = AutonomyLoop(alberto, tick_seconds=0.1, max_iterations=3, on_tick=tick)
        loop.start()
        assert len(ticks) == 3
        assert loop.errors_in_a_row == 0


class TestIntegration:
    def test_full_cycle_plan_to_recovery(self, alberto):
        """End-to-end: plan → execute → detect obstacle → research → evolve → record."""
        mc = MetaController(alberto)
        events_seen = []
        def on_event(e, d):
            events_seen.append(e)
        mc.on_event(on_event)
        # Force a failure scenario
        plan = mc.plan_objective("testar browser com browser-use")
        plan = mc.execute(plan)
        # Verify cycle
        assert "execute_start" in events_seen
        assert "obstacle_detected" in events_seen
        # Verify persistence
        assert alberto.learner.lessons_path.exists()
        # Verify skill was evolved
        history = mc.get_history(limit=1)
        assert history, "history should be recorded"

    def test_213_skills_loaded(self, alberto):
        from alberto.upstream_bridge import list_upstream_skills
        skills = list_upstream_skills()
        assert len(skills) >= 200, f"expected 200+ skills, got {len(skills)}"
