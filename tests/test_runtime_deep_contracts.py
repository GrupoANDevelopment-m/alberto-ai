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
