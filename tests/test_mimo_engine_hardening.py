"""MiMo engine hardening tests for path safety and bounded parallelism."""
from pathlib import Path
from types import SimpleNamespace

from alberto.engines.mimo import MiMoEngine


class FakeRouter:
    def __init__(self):
        self.calls = 0

    def invoke(self, task, messages, **kwargs):
        self.calls += 1
        return {"choices": [{"message": {"content": "generated response"}}]}


def make_engine(tmp_path):
    home = tmp_path / "agent-home"
    home.mkdir()
    router = FakeRouter()
    engine = MiMoEngine(SimpleNamespace(home=lambda: home), router,
                        mimo_home=home / ".mimo", auto_build=False)
    return engine, router, home


def test_snapshot_rejects_path_traversal_and_accepts_slug(tmp_path):
    engine, _, home = make_engine(tmp_path)
    try:
        bad = engine.snapshot("../../outside")
        assert bad["ok"] is False
        assert not (home / "outside.json").exists()
        good = engine.snapshot("safe_snapshot-1")
        assert good["ok"] is True
        assert (home / ".mimo" / "snapshots" / "safe_snapshot-1.json").is_file()
    finally:
        engine.stop()


def test_restore_snapshot_rejects_path_traversal(tmp_path):
    engine, _, home = make_engine(tmp_path)
    try:
        result = engine.restore_snapshot("../../outside")
        assert result["ok"] is False
        assert not (home / "outside.json").exists()
    finally:
        engine.stop()


def test_max_mode_bounds_parallel_workers_without_calling_provider(tmp_path):
    engine, router, _ = make_engine(tmp_path)
    try:
        for n in (0, -1, 9, True, 1.5):
            result = engine.max_mode("prompt", n=n)
            assert result["ok"] is False
        assert router.calls == 0
    finally:
        engine.stop()


def test_subagent_bounds_parallel_workers_without_calling_provider(tmp_path):
    engine, router, _ = make_engine(tmp_path)
    try:
        for count in (0, -2, 9, True, 2.5):
            result = engine.subagent("prompt", count=count)
            assert result and result[0]["ok"] is False
        assert router.calls == 0
    finally:
        engine.stop()


def test_compose_routes_code_generation_through_engine_invoke(tmp_path, monkeypatch):
    engine, _, _ = make_engine(tmp_path)
    calls = []

    def fake_invoke(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return "non-empty generated plan"

    monkeypatch.setattr(engine, "invoke", fake_invoke)
    monkeypatch.setattr(engine, "judge", lambda candidate: {"verdict": "pass", "score": 1.0})
    try:
        result = engine.compose("Build a todo app", steps=["spec", "tdd"])
        assert list(result) == ["spec", "tdd"]
        assert len(calls) == 2
        assert all(kwargs["task"] == "code" for _, kwargs in calls)
        assert all(result[step]["content"] == "non-empty generated plan" for step in result)
    finally:
        engine.stop()


def test_memory_upsert_is_searchable_and_does_not_break_updates(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    try:
        engine.memory_set("project.goal", "first goal", tags="project")
        engine.memory_set("project.goal", "second goal", tags="project")
        assert engine.memory_get("project.goal") == "second goal"
        entries = engine.memory_search('"second"')
        assert any(entry["key"] == "project.goal" for entry in entries)
    finally:
        engine.stop()
