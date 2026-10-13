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

def test_build_uses_real_upstream_workspace_entrypoint(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import alberto.engines.mimo as mimo_module

    home = tmp_path / "home"
    home.mkdir()
    upstream = tmp_path / "upstream-mimo"
    entry = upstream / "packages" / "opencode" / "src" / "index.ts"
    entry.parent.mkdir(parents=True)
    entry.write_text("export {}\n")
    engine = MiMoEngine(SimpleNamespace(home=lambda: home), FakeRouter(),
                        mimo_home=home / ".mimo", auto_build=False)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        target = Path(args[args.index("--outfile") + 1])
        target.write_text("#!/bin/sh\nexit 0\n")
        target.chmod(0o700)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mimo_module, "upstream_path", lambda _path: upstream)
    monkeypatch.setattr(mimo_module.shutil, "which", lambda name: "/usr/bin/bun" if name == "bun" else None)
    monkeypatch.setattr(mimo_module.subprocess, "run", fake_run)
    try:
        engine._try_build_binary()
        assert engine.binary == str(home / ".mimo" / "bin" / "mimo")
        args, kwargs = calls[0]
        assert str(entry) in args
        assert kwargs["cwd"] == str(upstream)
        assert kwargs["timeout"] == 180
    finally:
        engine.stop()


def test_failed_mimo_build_does_not_adopt_partial_output(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import alberto.engines.mimo as mimo_module

    home = tmp_path / "home"
    home.mkdir()
    upstream = tmp_path / "upstream-mimo"
    entry = upstream / "packages" / "opencode" / "src" / "index.ts"
    entry.parent.mkdir(parents=True)
    entry.write_text("export {}\n")
    engine = MiMoEngine(SimpleNamespace(home=lambda: home), FakeRouter(),
                        mimo_home=home / ".mimo", auto_build=False)

    def fake_run(args, **kwargs):
        target = Path(args[args.index("--outfile") + 1])
        target.write_text("partial")
        target.chmod(0o700)
        return SimpleNamespace(returncode=1, stdout="", stderr="build failed")

    monkeypatch.setattr(mimo_module, "upstream_path", lambda _path: upstream)
    monkeypatch.setattr(mimo_module.shutil, "which", lambda name: "/usr/bin/bun" if name == "bun" else None)
    monkeypatch.setattr(mimo_module.subprocess, "run", fake_run)
    try:
        engine._try_build_binary()
        assert engine.binary is None
    finally:
        engine.stop()

def test_binary_invoke_uses_supported_run_command_and_mimo_home(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import alberto.engines.mimo as mimo_module

    engine, router, home = make_engine(tmp_path)
    calls = []
    engine._binary = "/opt/mimo/bin/mimo"

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="MiMo generated code", stderr="")

    monkeypatch.setattr(mimo_module.subprocess, "run", fake_run)
    try:
        result = engine.invoke("Build a calculator", task="code")
        assert result == "MiMo generated code"
        args, kwargs = calls[0]
        assert args == ["/opt/mimo/bin/mimo", "run", "Build a calculator"]
        assert kwargs["env"]["MIMOCODE_HOME"] == str(home / ".mimo")
        assert "--session" not in args
        assert router.calls == 0
    finally:
        engine.stop()


def test_binary_invoke_falls_back_to_model_router_on_cli_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import alberto.engines.mimo as mimo_module

    engine, router, _ = make_engine(tmp_path)
    engine._binary = "/opt/mimo/bin/mimo"
    monkeypatch.setattr(
        mimo_module.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failed"),
    )
    try:
        result = engine.invoke("Build a calculator", task="code")
        assert result == "generated response"
        assert router.calls == 1
    finally:
        engine.stop()

def test_judge_fails_closed_on_malformed_json_and_substring_tricks(tmp_path):
    from types import SimpleNamespace

    engine, _, _ = make_engine(tmp_path)
    try:
        engine._router = SimpleNamespace(invoke=lambda *a, **k: {
            "choices": [{"message": {"content": "This does not pass the criteria"}}]
        })
        verdict = engine.judge("candidate")
        assert verdict["verdict"] == "fail"
        assert verdict["score"] == 0.0

        engine._router = SimpleNamespace(invoke=lambda *a, **k: {
            "choices": [{"message": {"content": '{"verdict":"pass","score":9,"reason":"ok"}'}}]
        })
        verdict = engine.judge("candidate")
        assert verdict == {"verdict": "pass", "score": 1.0, "reason": "ok"}

        engine._router = SimpleNamespace(invoke=lambda *a, **k: {
            "choices": [{"message": {"content": '{"verdict":"pass","score":NaN,"reason":false}'}}]
        })
        verdict = engine.judge("candidate")
        assert verdict["verdict"] == "pass"
        assert verdict["score"] == 0.0
        assert verdict["reason"] == "False"
    finally:
        engine.stop()
