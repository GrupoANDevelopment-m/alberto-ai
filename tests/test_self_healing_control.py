"""Regression tests for self-healing dry-run and apply behavior."""
import os
from types import SimpleNamespace

from alberto.runtime.function_caller import tool_heal_attempt
from alberto.runtime.self_healing import SelfHealer


class RecordingLearner:
    def __init__(self):
        self.lessons = []

    def lesson_learned(self, **kwargs):
        self.lessons.append(kwargs)


def make_healer():
    healer = SelfHealer.__new__(SelfHealer)
    healer.history = []
    healer._save = lambda: None
    learner = RecordingLearner()
    healer.alberto = SimpleNamespace(learner=learner)
    calls = []

    def detect(error, context):
        return "recoverable" in error

    def repair(error, context):
        calls.append((error, context))
        return {"fix": "repair_sample", "ok": True}

    healer.fixers = [(detect, repair)]
    return healer, learner, calls


def test_auto_apply_false_only_reports_matching_repairs():
    healer, learner, calls = make_healer()
    result = healer.attempt_heal(RuntimeError("recoverable failure"), auto_apply=False)

    assert result["matched_fixers"] == ["detect"]
    assert result["fixed"] is False
    assert result["actions"] == []
    assert result["applied"] == []
    assert calls == []
    assert learner.lessons == []


def test_tool_heal_attempt_supports_dry_run_without_signature_error():
    healer, learner, calls = make_healer()
    alberto = SimpleNamespace(healer=healer)

    output, is_error = tool_heal_attempt(
        alberto, {"error": "recoverable failure", "auto_apply": False}
    )

    assert is_error is True
    assert "MATCHED but not applied" in output
    assert calls == []
    assert learner.lessons == []


def test_auto_apply_true_executes_matching_repair():
    healer, learner, calls = make_healer()
    result = healer.attempt_heal(RuntimeError("recoverable failure"), auto_apply=True)

    assert result["fixed"] is True
    assert result["applied"] == ["repair_sample"]
    assert len(result["actions"]) == 1
    assert len(calls) == 1
    assert learner.lessons == []


def test_tool_heal_attempt_rejects_non_boolean_auto_apply():
    healer, learner, calls = make_healer()
    alberto = SimpleNamespace(healer=healer)

    output, is_error = tool_heal_attempt(
        alberto, {"error": "recoverable failure", "auto_apply": "false"}
    )

    assert is_error is True
    assert "must be a boolean" in output
    assert calls == []
    assert learner.lessons == []


def test_tool_heal_attempt_applies_only_when_explicitly_true():
    healer, learner, calls = make_healer()
    alberto = SimpleNamespace(healer=healer)

    output, is_error = tool_heal_attempt(
        alberto, {"error": "recoverable failure", "auto_apply": True}
    )

    assert is_error is False
    assert "FIXED" in output
    assert len(calls) == 1
    assert learner.lessons == []


def test_tls_recovery_never_copies_another_providers_key(monkeypatch):
    for key in list(os.environ):
        if key.startswith("NVIDIA_API_KEY_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-current-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-other-test-key")
    healer = SelfHealer.__new__(SelfHealer)

    result = healer._fix_tls_error("TLS certificate error", "test")

    assert result["ok"] is False
    assert os.environ["NVIDIA_API_KEY"] == "nvidia-current-test-key"


def test_tls_recovery_rotates_to_nvidia_backup_only(monkeypatch):
    for key in list(os.environ):
        if key.startswith("NVIDIA_API_KEY_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-current-test-key")
    monkeypatch.setenv("NVIDIA_API_KEY_BACKUP", "nvidia-backup-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-other-test-key")
    healer = SelfHealer.__new__(SelfHealer)

    result = healer._fix_tls_error("TLS certificate error", "test")

    assert result["ok"] is True
    assert result["switched_to"] == "NVIDIA_API_KEY_BACKUP"
    assert os.environ["NVIDIA_API_KEY"] == "nvidia-backup-test-key"



def test_auto_apply_stops_after_first_successful_repair():
    healer, learner, calls = make_healer()
    second_calls = []

    def second_detect(error, context):
        return True

    def second_repair(error, context):
        second_calls.append(True)
        return {"fix": "must_not_run", "ok": True}

    healer.fixers.append((second_detect, second_repair))
    result = healer.attempt_heal(RuntimeError("recoverable failure"), auto_apply=True)

    assert result["fixed"] is True
    assert result["applied"] == ["repair_sample"]
    assert len(calls) == 1
    assert second_calls == []
    assert learner.lessons == []
