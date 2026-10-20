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
        # The old indexed terms must disappear after an upsert.
        assert not any(entry["key"] == "project.goal" for entry in engine.memory_search('"first"'))
        assert engine.memory_delete("project.goal") is True
        assert not any(entry["key"] == "project.goal" for entry in engine.memory_search('"second"'))
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

def test_max_mode_does_not_judge_provider_error_messages(tmp_path, monkeypatch):
    from types import SimpleNamespace

    engine, _, _ = make_engine(tmp_path)
    monkeypatch.setattr(engine._router, "invoke", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    judged = []
    monkeypatch.setattr(engine, "judge", lambda candidate: judged.append(candidate) or {
        "verdict": "pass", "score": 1.0, "reason": "should not be called"
    })
    try:
        result = engine.max_mode("generate code", n=2)
        assert result["ok"] is False
        assert "all candidate generations failed" in result["error"]
        assert judged == []
    finally:
        engine.stop()



def test_lifecycle_reports_binary_failure_and_disables_bad_binary(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import alberto.engines.mimo as mimo_module

    engine, _, _ = make_engine(tmp_path)
    engine._binary = "/bad/mimo"
    monkeypatch.setattr(mimo_module.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=2))
    try:
        engine.start()
        assert engine.is_running() is False
        # Non-zero version status marks the engine not running but keeps the
        # path for diagnostic/retry purposes.
        assert engine.binary == "/bad/mimo"
        engine._binary = "/bad/mimo"
        monkeypatch.setattr(mimo_module.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("missing")))
        engine.start()
        assert engine.is_running() is False
        assert engine.binary is None
    finally:
        engine.stop()


def test_lifecycle_info_and_stop_are_idempotent(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    try:
        assert engine.info.name == "MiMo"
        assert engine.info.running is False
        engine.start()
        assert engine.is_running() is True
        engine.stop()
        engine.stop()
        assert engine.is_running() is False
    finally:
        engine.stop()


def test_goal_lifecycle_persists_goal_and_criteria(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    try:
        engine.goal_set("Ship safe app", success_criteria="all tests pass")
        assert engine.goal_get() == "Ship safe app"
        assert engine.memory_get("__goal_criteria__") == "all tests pass"
        engine.goal_clear()
        assert engine.goal_get() is None
        assert engine.memory_get("__goal_criteria__") is None
    finally:
        engine.stop()


def test_judge_provider_failure_returns_unknown(tmp_path):
    engine, _, _ = make_engine(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("provider offline")

    engine._router = SimpleNamespace(invoke=fail)
    try:
        result = engine.judge("candidate")
        assert result["verdict"] == "unknown"
        assert result["score"] == 0.0
        assert "provider offline" in result["reason"]
    finally:
        engine.stop()


def test_max_mode_selects_pass_before_higher_scored_failure(tmp_path, monkeypatch):
    engine, router, _ = make_engine(tmp_path)
    responses = iter(["candidate A", "candidate B"])
    monkeypatch.setattr(router, "invoke", lambda *a, **k: {
        "choices": [{"message": {"content": next(responses)}}]
    })
    verdicts = iter([
        {"verdict": "fail", "score": 1.0, "reason": "fails criterion"},
        {"verdict": "pass", "score": 0.5, "reason": "passes criterion"},
    ])
    monkeypatch.setattr(engine, "judge", lambda candidate: next(verdicts))
    try:
        result = engine.max_mode("write code", n=2)
        assert result["ok"] is True
        assert result["winner"]["content"] == "candidate B"
        assert result["winner"]["verdict"]["verdict"] == "pass"
    finally:
        engine.stop()


def test_max_mode_handles_empty_candidate_without_judging(tmp_path, monkeypatch):
    engine, router, _ = make_engine(tmp_path)
    responses = iter(["", "usable"])
    monkeypatch.setattr(router, "invoke", lambda *a, **k: {
        "choices": [{"message": {"content": next(responses)}}]
    })
    judged = []
    monkeypatch.setattr(engine, "judge", lambda candidate: judged.append(candidate) or {
        "verdict": "pass", "score": 1.0, "reason": "ok"
    })
    try:
        result = engine.max_mode("write code", n=2)
        assert result["ok"] is True
        assert result["all"][-1]["content"] == ""
        assert judged == ["usable"]
    finally:
        engine.stop()


def test_compose_records_failed_step_and_continues(tmp_path, monkeypatch):
    engine, _, _ = make_engine(tmp_path)
    calls = iter(["first output", "", "third output"])
    monkeypatch.setattr(engine, "invoke", lambda *a, **k: next(calls))
    monkeypatch.setattr(engine, "judge", lambda candidate: {"verdict": "pass", "score": 1})
    try:
        result = engine.compose("spec", steps=["spec", "tdd", "review"])
        assert result["spec"]["content"] == "first output"
        assert result["tdd"]["verdict"]["verdict"] == "fail"
        assert "empty compose result" in result["tdd"]["content"]
        assert result["review"]["content"] == "third output"
    finally:
        engine.stop()


def test_subagent_returns_success_and_failure_per_worker(tmp_path, monkeypatch):
    engine, router, _ = make_engine(tmp_path)
    calls = {"count": 0}

    def mixed(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("worker failed")
        return {"choices": [{"message": {"content": "worker output"}}]}

    monkeypatch.setattr(router, "invoke", mixed)
    try:
        results = engine.subagent("parallel task", count=2)
        assert len(results) == 2
        assert {item["ok"] for item in results} == {True, False}
        assert any(item.get("content") == "worker output" for item in results)
        assert any("worker failed" in item.get("error", "") for item in results)
    finally:
        engine.stop()


def test_distill_handles_empty_memory_provider_success_and_failure(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    try:
        assert "(empty)" in engine.distill()
        engine.memory_set("architecture", "Use least privilege and isolated execution")
        engine._router = SimpleNamespace(invoke=lambda *a, **k: {
            "choices": [{"message": {"content": "# Memory\n- Least privilege"}}]
        })
        assert "Least privilege" in engine.distill()
        assert engine.memory_get("__distilled__") is not None

        engine._router = SimpleNamespace(invoke=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        assert "Distillation failed" in engine.distill()
    finally:
        engine.stop()


def test_sessions_checkpoints_and_snapshot_restore_round_trip(tmp_path):
    engine, _, home = make_engine(tmp_path)
    try:
        engine.memory_set("persisted", "remember me", tags="test")
        session = engine.session_create(goal="verify restore")
        listed = engine.session_list()
        assert any(item["id"] == session.id for item in listed)
        session_file = home / ".mimo" / "sessions" / f"{session.id}.json"
        assert session_file.is_file()

        checkpoint = engine.checkpoint(session.id, "before test")
        assert checkpoint["note"] == "before test"
        assert checkpoint["memory_keys"] >= 1
        assert list((home / ".mimo" / "checkpoints").glob(f"{session.id}-*.json"))
        assert "unknown session" in engine.checkpoint("missing-session")["error"]

        saved = engine.snapshot("roundtrip")
        assert saved["ok"] is True
        engine.memory_delete("persisted")
        restored = engine.restore_snapshot("roundtrip")
        assert restored["ok"] is True
        assert engine.memory_get("persisted") == "remember me"
        assert engine.restore_snapshot("does-not-exist").get("error")
    finally:
        engine.stop()


def test_memory_search_invalid_query_and_delete_missing_key_are_safe(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    try:
        assert engine.memory_search('"unterminated') == []
        assert engine.memory_delete("absent") is True
        assert engine.memory_get("absent") is None
    finally:
        engine.stop()


def test_auto_build_falls_back_if_upstream_or_bun_missing(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import alberto.engines.mimo as mimo_module

    home = tmp_path / "home"
    home.mkdir()
    engine = MiMoEngine(SimpleNamespace(home=lambda: home), FakeRouter(),
                        mimo_home=home / ".mimo", auto_build=False)
    monkeypatch.setattr(mimo_module, "upstream_path", lambda _path: tmp_path / "missing-upstream")
    monkeypatch.setattr(mimo_module.shutil, "which", lambda _name: None)
    try:
        engine._try_build_binary()
        assert engine.binary is None
    finally:
        engine.stop()


def test_binary_start_exception_disables_binary(tmp_path, monkeypatch):
    import alberto.engines.mimo as mimo_module

    engine, _, _ = make_engine(tmp_path)
    engine._binary = "/bad/mimo"
    monkeypatch.setattr(mimo_module.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timeout")))
    try:
        engine.start()
        assert engine.is_running() is False
        assert engine.binary is None
    finally:
        engine.stop()


def test_memory_search_rejects_unbounded_or_invalid_limits(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    try:
        engine.memory_set("resource.test", "bounded memory search")
        for limit in (0, -1, 101, True, 1.5, "10", None):
            try:
                engine.memory_search("bounded", limit=limit)
            except ValueError as exc:
                assert "limit" in str(exc).lower()
            else:
                raise AssertionError(f"invalid memory search limit accepted: {limit!r}")
    finally:
        engine.stop()


def test_memory_search_rejects_non_string_query(tmp_path):
    engine, _, _ = make_engine(tmp_path)
    try:
        for query in (None, 123, ["term"]):
            try:
                engine.memory_search(query)
            except ValueError as exc:
                assert "query" in str(exc).lower()
            else:
                raise AssertionError(f"invalid memory search query accepted: {query!r}")
    finally:
        engine.stop()

def test_session_list_rehydrates_persisted_sessions_and_checkpoints(tmp_path):
    engine, _, home = make_engine(tmp_path)
    session = engine.session_create(goal="audit recovery")
    checkpoint = engine.checkpoint(session.id, "before restart")
    assert "error" not in checkpoint
    engine.stop()

    restarted = MiMoEngine(
        SimpleNamespace(home=lambda: home), FakeRouter(),
        mimo_home=home / ".mimo", auto_build=False,
    )
    try:
        sessions = restarted.session_list()
        assert len(sessions) == 1
        assert sessions[0]["id"] == session.id
        assert sessions[0]["goal"] == "audit recovery"
        assert any(item["note"] == "before restart" for item in sessions[0]["checkpoints"])
    finally:
        restarted.stop()


def test_snapshot_restore_restores_sessions_and_memory_after_validation(tmp_path):
    engine, _, home = make_engine(tmp_path)
    session = engine.session_create(goal="snapshot goal")
    engine.checkpoint(session.id, "checkpoint included")
    engine.memory_set("project.key", "snapshot value", tags="audit")
    snap = engine.snapshot("full-state")
    assert snap["ok"] is True

    engine.memory_set("project.key", "mutated value", tags="changed")
    engine.session_create(goal="must be replaced")
    restored = engine.restore_snapshot("full-state")
    assert restored == {"ok": True, "restored": len(engine.memory_list()), "sessions_restored": 1}
    assert engine.memory_get("project.key") == "snapshot value"
    sessions = engine.session_list()
    assert len(sessions) == 1
    assert sessions[0]["id"] == session.id
    assert any(item["note"] == "checkpoint included" for item in sessions[0]["checkpoints"])
    engine.stop()

    restarted = MiMoEngine(
        SimpleNamespace(home=lambda: home), FakeRouter(),
        mimo_home=home / ".mimo", auto_build=False,
    )
    try:
        assert restarted.memory_get("project.key") == "snapshot value"
        assert any(item["id"] == session.id for item in restarted.session_list())
    finally:
        restarted.stop()


def test_restore_snapshot_rejects_corrupt_or_invalid_payload_without_mutation(tmp_path):
    import json

    engine, _, home = make_engine(tmp_path)
    try:
        engine.memory_set("keep", "original")
        snapshots = home / ".mimo" / "snapshots"
        (snapshots / "broken.json").write_text("{invalid", encoding="utf-8")
        result = engine.restore_snapshot("broken")
        assert result["ok"] is False
        assert engine.memory_get("keep") == "original"

        (snapshots / "bad-schema.json").write_text(json.dumps({
            "name": "bad-schema",
            "entries": [{"key": "new", "value": "would partially restore"}, {"key": "", "value": 7}],
            "sessions": [],
        }), encoding="utf-8")
        result = engine.restore_snapshot("bad-schema")
        assert result["ok"] is False
        assert engine.memory_get("keep") == "original"
        assert engine.memory_get("new") is None
    finally:
        engine.stop()

def test_snapshot_restore_rolls_back_memory_and_files_on_publish_failure(tmp_path, monkeypatch):
    import alberto.engines.mimo as mimo_module

    engine, _, home = make_engine(tmp_path)
    try:
        engine.memory_set("keep", "original value")
        original = engine.session_create(goal="original session")
        engine.checkpoint(original.id, "original checkpoint")
        snapshot = engine.snapshot("rollback-case")
        assert snapshot["ok"] is True

        engine.memory_set("keep", "mutated value")
        extra = engine.session_create(goal="session to remove")
        live_sessions = home / ".mimo" / "sessions"
        live_checkpoints = home / ".mimo" / "checkpoints"
        original_session_bytes = {
            path.name: path.read_bytes() for path in live_sessions.glob("*.json")
        }
        original_checkpoint_bytes = {
            path.name: path.read_bytes() for path in live_checkpoints.glob("*.json")
        }
        real_replace = mimo_module.os.replace

        def fail_checkpoint_publish(src, dst):
            src_path, dst_path = Path(src), Path(dst)
            if (dst_path == live_checkpoints
                    and src_path.name == "checkpoints"
                    and src_path.parent.name.startswith(".restore-")):
                raise OSError("injected checkpoint publish failure")
            return real_replace(src, dst)

        monkeypatch.setattr(mimo_module.os, "replace", fail_checkpoint_publish)
        result = engine.restore_snapshot("rollback-case")
        assert result["ok"] is False
        assert "prior state retained" in result["error"]
        assert engine.memory_get("keep") == "mutated value"
        assert {p.name: p.read_bytes() for p in live_sessions.glob("*.json")} == original_session_bytes
        assert {p.name: p.read_bytes() for p in live_checkpoints.glob("*.json")} == original_checkpoint_bytes
        assert {item["id"] for item in engine.session_list()} == {original.id, extra.id}
    finally:
        engine.stop()
