"""Regression tests for safe self-healing control flow."""
from types import SimpleNamespace

from alberto.runtime.self_healing import SelfHealer


def test_stops_after_first_successful_repair():
    healer = SelfHealer.__new__(SelfHealer)
    healer.history = []
    healer._save = lambda: None
    healer.alberto = SimpleNamespace(learner=None)
    calls = []

    def detect_first(error, context):
        return True

    def fix_first(error, context):
        calls.append("first")
        return {"fix": "first", "ok": True}

    def detect_second(error, context):
        return True

    def fix_second(error, context):
        calls.append("second")
        return {"fix": "second", "ok": True}

    healer.fixers = [
        (detect_first, fix_first),
        (detect_second, fix_second),
    ]

    result = healer.attempt_heal(RuntimeError("recoverable"), context="test")

    assert result["fixed"] is True
    assert calls == ["first"]
    assert len(result["actions"]) == 1


def test_continues_when_matching_repair_fails():
    healer = SelfHealer.__new__(SelfHealer)
    healer.history = []
    healer._save = lambda: None
    healer.alberto = SimpleNamespace(learner=None)
    calls = []

    def detect(error, context):
        return True

    def failed_fix(error, context):
        calls.append("failed")
        return {"fix": "failed", "ok": False}

    def successful_fix(error, context):
        calls.append("successful")
        return {"fix": "successful", "ok": True}

    healer.fixers = [(detect, failed_fix), (detect, successful_fix)]

    result = healer.attempt_heal(RuntimeError("recoverable"), context="test")

    assert result["fixed"] is True
    assert calls == ["failed", "successful"]
    assert len(result["actions"]) == 2
