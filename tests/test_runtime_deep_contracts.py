"""Deep contract tests for runtime behavior; no import-only/smoke assertions.

These tests exercise persisted audit events, bounded recent-event retrieval, loop
lifecycle/error policy, and the CrewAI workflow-to-agent/task orchestration path.
External LLM network calls are isolated at the provider boundary; YAML parsing,
filesystem reads, orchestration decisions and result formatting remain real.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alberto.runtime import audit, autonomy, crewai_runtime


# ---------- Persistent audit log: actual filesystem behavior ----------

def test_audit_round_trip_redaction_and_recent_window(tmp_path, monkeypatch):
    path = tmp_path / ".alberto" / "audit.log"
    monkeypatch.setattr(audit, "AUDIT_PATH", path)

    audit.log_tool_call(
        "write_file",
        {"path": "result.txt", "content": "x" * 250, "command": "echo secret"},
        ("ok", False),
        user_confirmed=True,
    )
    audit.log_blocked_shell("rm -rf /", "dangerous recursive delete")
    events = audit.get_recent_events(1)

    assert path.is_file()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert len(events) == 1
    assert events[0]["type"] == "blocked_shell"
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first["tool"] == "write_file"
    assert first["user_confirmed"] is True
    assert first["args"]["content"].endswith("...")
    assert len(first["args"]["content"]) == 203
    assert first["result_is_err"] is False


def test_audit_reader_skips_corrupt_lines_and_clear_returns_line_count(tmp_path, monkeypatch):
    path = tmp_path / "audit.log"
    monkeypatch.setattr(audit, "AUDIT_PATH", path)
    path.write_text('{"type":"valid"}\nnot-json\n\n{"type":"also-valid"}\n', encoding="utf-8")

    assert [e["type"] for e in audit.get_recent_events(10)] == ["valid", "also-valid"]
    assert audit.clear_audit_log() == 4
    assert not path.exists()
    assert audit.get_recent_events() == []


def test_audit_write_failure_is_non_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "missing-parent" / "audit.log")

    def fail(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(audit, "_ensure_audit_path", fail)
    audit.log_event("test", {"value": 1})  # documented best-effort logging contract


# ---------- Autonomy loop: actual lifecycle and failure threshold ----------

def _patch_loop_runtime(monkeypatch):
    monkeypatch.setattr(autonomy.signal, "signal", lambda *args: None)
    monkeypatch.setattr(autonomy.time, "sleep", lambda seconds: None)


def test_autonomy_loop_runs_exact_iteration_count_and_stops_cleanly(monkeypatch, capsys):
    _patch_loop_runtime(monkeypatch)
    ticks = []
    loop = autonomy.AutonomyLoop(object(), tick_seconds=0.1, max_iterations=3,
                                 on_tick=lambda: ticks.append("tick"))
    loop.start()

    assert ticks == ["tick", "tick", "tick"]
    assert loop.iteration == 3
    assert loop._running is False
    assert "stopped" in capsys.readouterr().out


def test_autonomy_loop_stops_after_five_consecutive_tick_errors(monkeypatch):
    _patch_loop_runtime(monkeypatch)
    calls = []

    def broken_tick():
        calls.append(1)
        raise RuntimeError("worker failed")

    loop = autonomy.AutonomyLoop(object(), tick_seconds=0.1, on_tick=broken_tick)
    loop.start()

    assert len(calls) == 5
    assert loop.errors_in_a_row == 5
    assert loop._running is False


def test_autonomy_default_tick_executes_both_available_integrations():
    calls = []
    class Worker:
        def cron_run_pending(self):
            calls.append("cron")
        def watchers_check(self):
            calls.append("watchers")

    autonomy.AutonomyLoop(Worker(), tick_seconds=0.1)._default_tick()
    assert calls == ["cron", "watchers"]


def test_autonomy_default_tick_isolates_one_integration_failure():
    calls = []
    class Worker:
        def cron_run_pending(self):
            calls.append("cron")
            raise RuntimeError("cron storage unavailable")
        def watchers_check(self):
            calls.append("watchers")

    autonomy.AutonomyLoop(Worker(), tick_seconds=0.1)._default_tick()
    assert calls == ["cron", "watchers"]


# ---------- CrewAI workflow orchestration: real YAML/filesystem, provider boundary isolated ----------

def _write_workflow(tmp_path: Path, *, workflow=None, personas=None):
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text(
        __import__("yaml").safe_dump({
            "name": "contract-suite",
            "personas": personas if personas is not None else [
                {"name": "planner", "role": "Planner", "system_prompt": "Plan carefully."},
                {"name": "builder", "role": "Builder", "system_prompt": "Build safely."},
            ],
            "workflow": workflow if workflow is not None else [
                {"persona": "planner", "task": "Plan for {user}", "output_to": "plan"},
                {"persona": "builder", "task": "Implement the plan", "output_to": "build"},
            ],
        }),
        encoding="utf-8",
    )
    return workflow_path


def _install_crewai_boundary(monkeypatch, *, kickoff_result="completed", kickoff_errors=()):
    """Use production workflow parsing/validation; isolate only provider/framework boundary."""
    agents, tasks, crews = [], [], []
    class Agent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            agents.append(self)
    class Task:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            tasks.append(self)
    class Crew:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            crews.append(self)
        def kickoff(self):
            if kickoff_errors:
                error = kickoff_errors.pop(0)
                raise error
            return kickoff_result
    class Process:
        sequential = "sequential"

    monkeypatch.setattr(crewai_runtime, "_try_load_crewai", lambda: True)
    monkeypatch.setattr(crewai_runtime, "_Agent", Agent)
    monkeypatch.setattr(crewai_runtime, "_Task", Task)
    monkeypatch.setattr(crewai_runtime, "_Crew", Crew)
    monkeypatch.setattr(crewai_runtime, "_Process", Process)
    monkeypatch.setattr(crewai_runtime, "_LLM", lambda **kwargs: SimpleNamespace(config=kwargs))
    return agents, tasks, crews


def test_crewai_executes_real_yaml_to_agent_task_pipeline_and_formats_output(tmp_path, monkeypatch):
    agents, tasks, crews = _install_crewai_boundary(monkeypatch, kickoff_result="deliverable: 42")
    workflow = _write_workflow(tmp_path)
    result = crewai_runtime.run_crew_squad(
        "contract-suite", str(workflow), str(tmp_path), llm_model="test/model",
        llm_api_key="non-secret-test-key", user_prompt="user request",
    )

    assert result == {
        "ok": True, "squad": "contract-suite", "engine": "crewai",
        "crewai_version": "1.15.23",
        "outputs": {"final": "deliverable: 42"}, "raw_result": "deliverable: 42",
    }
    assert len(agents) == 2 and len(tasks) == 2 and len(crews) == 1
    assert crews[0].kwargs["process"] == "sequential"
    assert [task.kwargs["agent"] for task in tasks] == agents
    assert "user request" in tasks[0].kwargs["description"]
    assert tasks[0].kwargs["expected_output"] == "Result for step 'plan'"


def test_crewai_rejects_unknown_persona_before_kickoff(tmp_path, monkeypatch):
    _, tasks, crews = _install_crewai_boundary(monkeypatch)
    workflow = _write_workflow(tmp_path, workflow=[
        {"persona": "missing", "task": "Do work", "output_to": "result"}
    ])
    result = crewai_runtime.run_crew_squad(
        "contract-suite", str(workflow), str(tmp_path), llm_api_key="test-key"
    )

    assert result["ok"] is False
    assert "not in agents" in result["error"]
    assert tasks == []
    assert crews == []


def test_crewai_missing_persona_file_fails_before_credentials(tmp_path, monkeypatch):
    _install_crewai_boundary(monkeypatch)
    workflow = _write_workflow(tmp_path, personas=[
        {"name": "missing-file", "role": "Reviewer"}
    ])
    result = crewai_runtime.run_crew_squad(
        "contract-suite", str(workflow), str(tmp_path), llm_api_key=None
    )

    assert result["ok"] is False
    assert "persona file missing" in result["error"]


def test_crewai_provider_setup_failure_is_reported_without_running_crew(tmp_path, monkeypatch):
    _, _, crews = _install_crewai_boundary(monkeypatch)
    monkeypatch.setattr(
        crewai_runtime, "_LLM",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("invalid provider config")),
    )
    workflow = _write_workflow(tmp_path)
    result = crewai_runtime.run_crew_squad(
        "contract-suite", str(workflow), str(tmp_path), llm_api_key="test-key"
    )

    assert result["ok"] is False
    assert "failed to build LLM" in result["error"]
    assert crews == []


def test_crewai_retries_rate_limit_and_returns_success(monkeypatch, tmp_path):
    errors = [RuntimeError("HTTP 429 rate limit"), RuntimeError("too many requests")]
    _, _, crews = _install_crewai_boundary(monkeypatch, kickoff_result="recovered", kickoff_errors=errors)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    workflow = _write_workflow(tmp_path)
    result = crewai_runtime.run_crew_squad(
        "contract-suite", str(workflow), str(tmp_path), llm_api_key="test-key"
    )

    assert result["ok"] is True
    assert result["raw_result"] == "recovered"
    assert len(crews) == 3


def test_crewai_non_rate_limit_failure_fails_fast(tmp_path, monkeypatch):
    _, _, crews = _install_crewai_boundary(
        monkeypatch, kickoff_errors=[RuntimeError("invalid task payload")]
    )
    workflow = _write_workflow(tmp_path)
    result = crewai_runtime.run_crew_squad(
        "contract-suite", str(workflow), str(tmp_path), llm_api_key="test-key"
    )

    assert result["ok"] is False
    assert "crew run failed: invalid task payload" in result["error"]
    assert len(crews) == 1


# ---------- Model router: real HTTP protocol and fallback against a local server ----------

def test_model_router_falls_back_after_real_http_error_and_sends_valid_payload(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from alberto.model_router import ModelConfig, ModelRouter, ModelSpec

    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((body, self.headers.get("Authorization"), self.path))
            if body["model"] == "primary":
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"temporarily unavailable")
                return
            response = {"choices": [{"message": {"role": "assistant", "content": "actual local HTTP response"}}]}
            raw = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setenv("PRIMARY_KEY", "primary-secret")
        monkeypatch.setenv("FALLBACK_KEY", "fallback-secret")
        primary = ModelSpec("local-primary", "primary", url, "PRIMARY_KEY")
        fallback = ModelSpec("local-fallback", "fallback", url + "/v1/", "FALLBACK_KEY",
                             options={"reasoning_effort": "low"})
        router = ModelRouter(ModelConfig(tasks={"reasoning": primary}, fallback_chain=[fallback]))

        result = router.invoke(
            "reasoning", [{"role": "user", "content": "calculate 6 * 7"}],
            max_tokens=77, temperature=0.2,
            tools=[{"type": "function", "function": {"name": "calc", "parameters": {"type": "object"}}}],
            tool_choice="auto",
        )

        assert result["choices"][0]["message"]["content"] == "actual local HTTP response"
        assert len(received) == 2
        assert received[0][0]["model"] == "primary"
        assert received[1][0]["model"] == "fallback"
        assert received[1][0]["reasoning_effort"] == "low"
        assert received[1][0]["max_tokens"] == 77
        assert received[1][0]["temperature"] == 0.2
        assert received[1][0]["tool_choice"] == "auto"
        assert received[1][0]["tools"][0]["function"]["name"] == "calc"
        assert received[0][1] == "Bearer primary-secret"
        assert received[1][1] == "Bearer fallback-secret"
        assert all(path == "/v1/chat/completions" for _, _, path in received)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_model_router_fails_closed_when_no_credential_or_model_is_configured(monkeypatch):
    from alberto.model_router import ModelConfig, ModelRouter, ModelSpec

    monkeypatch.delenv("NO_SUCH_CREDENTIAL", raising=False)
    router = ModelRouter(ModelConfig(tasks={
        "reasoning": ModelSpec("provider", "model", "http://127.0.0.1:1", "NO_SUCH_CREDENTIAL")
    }))
    with pytest.raises(RuntimeError, match="credential env"):
        router.invoke("reasoning", [{"role": "user", "content": "hello"}])

    with pytest.raises(RuntimeError, match="No model configured"):
        ModelRouter(ModelConfig(tasks={})).invoke("unknown", [])


# ---------- AppTester: actual local HTTP benchmark, not a process/import smoke test ----------

def test_app_tester_performs_real_local_http_load_and_reports_measurements(tmp_path, monkeypatch):
    from alberto.runtime.tester import AppTester, HOST_APP_EXECUTION_OPT_IN

    backend = tmp_path / "backend"
    backend.mkdir()
    # A deterministic local service fixture; the tester launches a real Uvicorn
    # process and issues actual HTTP requests against it.
    (backend / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'ok', 'value': 42}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(HOST_APP_EXECUTION_OPT_IN, "1")
    tester = AppTester(tmp_path)

    result = tester.perf("/health", n_requests=5, concurrency=2)

    assert result["phase"] == "perf"
    assert result["endpoint"] == "/health"
    assert result["n_requests"] == 5
    assert result["concurrency"] == 2
    assert result["ok"] is True
    assert result["sequential"]["n"] == 5
    assert result["sequential"]["errors"] == 0
    assert result["concurrent"]["n"] == 5
    assert result["concurrent"]["errors"] == 0
    assert result["concurrent"]["throughput_rps"] > 0
    assert result["sequential"]["p95_ms"] >= 0
    assert result["concurrent"]["p99_ms"] >= 0


# ---------- MetaController: execution policy and dependency behavior ----------

def test_meta_controller_refuses_host_skill_execution_without_opt_in(monkeypatch):
    from types import SimpleNamespace
    from alberto.runtime.meta_controller import MetaController, SubTask
    from alberto.runtime import skill_engine

    monkeypatch.delenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", raising=False)
    calls = []
    sandbox = SimpleNamespace(run=lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        skill_engine, "run_skill",
        lambda *args, **kwargs: calls.append(("run_skill", args, kwargs)),
    )
    controller = object.__new__(MetaController)
    controller.alberto = SimpleNamespace(sandbox=sandbox)

    ok, output, error = controller._try_skill(
        SubTask(id="st-1", description="execute a skill", skill="untrusted")
    )

    assert ok is False
    assert output is None
    assert "Docker isolation is required" in error
    assert calls == []


def test_meta_controller_executes_skill_through_docker_configured_sandbox(monkeypatch):
    from types import SimpleNamespace
    from alberto.runtime.meta_controller import MetaController, SubTask
    from alberto.runtime import skill_engine

    monkeypatch.delenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", raising=False)
    sandbox = SimpleNamespace(
        isolation_level="docker-container",
        _mode="docker",
        run=lambda *args, **kwargs: None,
    )
    calls = []

    def run_skill(name, args, *, sandbox, timeout):
        calls.append((name, args, sandbox, timeout))
        return {"ok": True, "stdout": "behavior verified"}

    monkeypatch.setattr(skill_engine, "run_skill", run_skill)
    controller = object.__new__(MetaController)
    controller.alberto = SimpleNamespace(sandbox=sandbox)

    result = controller._try_skill(
        SubTask(id="st-1", description="execute safe skill", skill="safe-skill")
    )

    assert result == (True, "behavior verified", "")
    assert calls == [("safe-skill", [], sandbox, 10)]


def test_meta_controller_policy_denial_does_not_trigger_auto_recovery(monkeypatch):
    from types import SimpleNamespace
    from alberto.runtime.meta_controller import MetaController, Plan, SubTask

    monkeypatch.delenv("ALBERTO_ALLOW_HOST_SKILL_EXECUTION", raising=False)
    sandbox = SimpleNamespace(run=lambda *args, **kwargs: None)
    controller = object.__new__(MetaController)
    controller.alberto = SimpleNamespace(sandbox=sandbox)
    controller._on_event = None

    def forbidden(*args, **kwargs):
        raise AssertionError("policy denial must not trigger learning or recovery")

    controller.skill_manager = SimpleNamespace(record_outcome=forbidden)
    controller.researcher = SimpleNamespace(search=forbidden)
    controller.learner = SimpleNamespace(
        lesson_learned=forbidden, evolve_skill=forbidden, overcome_obstacle=forbidden
    )
    task = SubTask(id="st-1", description="run untrusted code", skill="untrusted")
    plan = Plan(objective="run untrusted code", subtasks=[task])

    controller._execute_subtask(plan, task)

    assert task.status == "blocked"
    assert task.attempts == 1
    assert "skill execution refused:" in task.error


def test_meta_controller_blocks_dependents_after_failed_prerequisite():
    from alberto.runtime.meta_controller import MetaController, Plan, SubTask

    controller = object.__new__(MetaController)
    controller._on_event = None
    controller._record_plan = lambda plan: None
    attempted = []

    def execute_one(plan, task):
        attempted.append(task.id)
        task.status = "failed"
        task.error = "prerequisite failed"

    controller._execute_subtask = execute_one
    first = SubTask(id="st-1", description="first step", skill="first")
    second = SubTask(
        id="st-2", description="dependent step", skill="second", depends_on=["st-1"]
    )
    result = controller.execute(Plan(objective="ordered workflow", subtasks=[first, second]))

    assert attempted == ["st-1"]
    assert first.status == "failed"
    assert second.status == "blocked"
    assert "dependency not completed" in second.error
    assert result.status == "failed"
