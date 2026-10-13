"""Focused regression tests for SmartRouter selection, fallbacks and accounting."""
import json
from pathlib import Path
from types import SimpleNamespace

from alberto.runtime.smart_router import ModelSpec, ModelStats, SmartRouter


class FakeSandbox:
    def __init__(self, home):
        self._home = Path(home)

    def home(self):
        return self._home


def router(tmp_path):
    return SmartRouter(SimpleNamespace(sandbox=FakeSandbox(tmp_path)))


def spec(model, *, capability="chat", priority=50, cost=0.0, enabled=True):
    return ModelSpec(
        provider="test", model_id=model, base_url="https://provider.invalid/v1",
        credential_env="TEST_API_KEY", capability=capability,
        priority=priority, cost_per_1k_input=cost, enabled=enabled,
    )


def test_router_persists_and_restores_model_statistics(tmp_path):
    first = router(tmp_path)
    first.stats["model-a"] = ModelStats(calls=2, successes=1, failures=1, total_cost_usd=0.25)
    first._save_stats()

    second = router(tmp_path)
    assert second.stats["model-a"].calls == 2
    assert second.stats["model-a"].successes == 1
    assert second.total_cost() == 0.25


def test_corrupt_stats_file_fails_closed_to_empty_stats(tmp_path):
    r = router(tmp_path)
    r._stats_path.write_text("{invalid")
    fresh = router(tmp_path)
    assert fresh.stats == {}


def test_rank_prefers_matching_capability_then_falls_back_to_enabled(tmp_path):
    r = router(tmp_path)
    r.add_spec(spec("chat-low", capability="chat", priority=10))
    r.add_spec(spec("code-high", capability="code", priority=100))
    r.add_spec(spec("disabled", capability="chat", priority=1000, enabled=False))
    assert [s.model_id for s in r.rank_models("chat")] == ["chat-low"]
    assert [s.model_id for s in r.rank_models("vision")] == ["code-high", "chat-low"]


def test_rank_can_prefer_cheap_models(tmp_path):
    r = router(tmp_path)
    r.add_spec(spec("premium", priority=100, cost=0.1))
    r.add_spec(spec("cheap", priority=50, cost=0.0))
    assert r.rank_models("chat", prefer_cheap=True)[0].model_id == "cheap"


def test_recent_failure_is_temporarily_excluded(tmp_path, monkeypatch):
    r = router(tmp_path)
    bad, good = spec("bad", priority=100), spec("good", priority=10)
    r.add_spec(bad)
    r.add_spec(good)
    r.stats["bad"] = ModelStats(calls=1, failures=1, last_error="timeout", last_used=1000)
    monkeypatch.setattr("alberto.runtime.smart_router.time.time", lambda: 1010)
    assert [s.model_id for s in r.rank_models("chat")] == ["good"]


def test_complete_falls_back_after_provider_error_and_records_metrics(tmp_path, monkeypatch):
    r = router(tmp_path)
    bad, good = spec("bad", priority=100), spec("good", priority=10)
    r.add_spec(bad)
    r.add_spec(good)

    def fake_call(model, messages, max_tokens, temperature, stream):
        if model.model_id == "bad":
            raise TimeoutError("provider timeout")
        return {"ok": True, "content": "done", "input_tokens": 1000, "output_tokens": 500}

    monkeypatch.setattr(r, "_call", fake_call)
    result = r.complete([{"role": "user", "content": "hello"}])
    assert result["ok"] is True
    assert result["model_used"] == "good"
    assert r.stats["bad"].failures == 1
    assert r.stats["bad"].last_error == "provider timeout"
    assert r.stats["good"].successes == 1
    assert r.total_cost() == 0.0


def test_complete_reports_when_all_models_fail(tmp_path, monkeypatch):
    r = router(tmp_path)
    r.add_spec(spec("bad"))
    monkeypatch.setattr(r, "_call", lambda *args: (_ for _ in ()).throw(RuntimeError("offline")))
    result = r.complete([])
    assert result["ok"] is False
    assert "all 1 models failed" in result["error"]
    assert r.stats["bad"].failures == 1


def test_call_requires_credentials_before_network(tmp_path, monkeypatch):
    r = router(tmp_path)
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    with __import__("pytest").raises(RuntimeError, match="missing credential TEST_API_KEY"):
        r._call(spec("model"), [], 10, 0.0, False)


def test_call_normalizes_openai_compatible_response(tmp_path, monkeypatch):
    r = router(tmp_path)
    monkeypatch.setenv("TEST_API_KEY", "dummy")
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            }).encode()

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["auth"] = request.get_header("Authorization")
        seen["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = r._call(spec("model"), [{"role": "user", "content": "hi"}], 22, 0.2, False)
    assert seen["url"] == "https://provider.invalid/v1/chat/completions"
    assert seen["timeout"] == 60
    assert seen["auth"] == "Bearer dummy"
    assert seen["body"]["max_tokens"] == 22
    assert result == {"ok": True, "content": "hello", "input_tokens": 7, "output_tokens": 3}


def test_record_success_accumulates_cost_and_weighted_latency(tmp_path):
    r = router(tmp_path)
    s = spec("metered", cost=0.002)
    r._record_success(s, {"input_tokens": 1000, "output_tokens": 500}, 100)
    r._record_success(s, {"input_tokens": 1000, "output_tokens": 500}, 300)
    stats = r.stats["metered"]
    assert stats.calls == 2
    assert stats.total_input_tokens == 2000
    assert stats.total_output_tokens == 1000
    assert stats.avg_latency_ms == 200
    assert stats.total_cost_usd == 0.006


def test_load_specs_from_alberto_maps_pricing_and_fallbacks(tmp_path):
    task_spec = SimpleNamespace(provider="p", model_id="gpt-4o", base_url="https://api.invalid/v1",
                                credential_env="KEY")
    fallback = SimpleNamespace(provider="p2", model_id="claude-3", base_url="https://api2.invalid",
                               credential_env="KEY2")
    config = SimpleNamespace(tasks={"chat": task_spec}, fallback_chain=[fallback])
    r = router(tmp_path)
    r.alberto.router = SimpleNamespace(config=config)
    r._load_specs_from_alberto()
    assert [s.model_id for s in r.specs] == ["gpt-4o", "claude-3"]
    assert r.specs[0].cost_per_1k_input == 0.03
    assert r.specs[1].cost_per_1k_output == 0.024
