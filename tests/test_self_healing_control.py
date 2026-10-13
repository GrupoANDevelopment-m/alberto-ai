"""Regression tests for self-healing dry-run and apply behavior."""
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
