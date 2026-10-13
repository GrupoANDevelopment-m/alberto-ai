"""Unit tests for benchmark scoring and aggregation, not model-performance simulation."""
from scripts.benchmark_alberto import TASKS, score_response, summarize_results


def task(task_id):
    return next(item for item in TASKS if item["id"] == task_id)


def test_exact_scorer_requires_exact_instruction_output():
    assert score_response(task("instruction_token"), "READY\n") is True
    assert score_response(task("instruction_token"), "READY.") is False


def test_json_scorer_accepts_valid_object_and_rejects_wrong_values():
    assert score_response(
        task("json_status_count"),
        '{"status":"ok","count":3}',
    ) is True
    assert score_response(
        task("json_status_count"),
        '{"status":"ok","count":4}',
    ) is False
    assert score_response(task("json_status_count"), "not json") is False


def test_line_scorer_checks_exact_order_and_count():
    assert score_response(
        task("exact_three_lines"),
        "ITEM-1\nITEM-2\nITEM-3\n",
    ) is True
    assert score_response(
        task("exact_three_lines"),
        "ITEM-1\nITEM-3\nITEM-2\n",
    ) is False


def test_summary_metrics_use_recorded_values():
    summary = summarize_results([
        {"passed": True, "latency_ms": 100.0, "error": None},
        {"passed": True, "latency_ms": 200.0, "error": None},
        {"passed": False, "latency_ms": 300.0, "error": "provider timeout"},
    ])

    assert summary["cases"] == 3
    assert summary["passed"] == 2
    assert summary["pass_rate"] == 0.6667
    assert summary["errors"] == 1
    assert summary["median_latency_ms"] == 200.0
    assert summary["p95_latency_ms"] == 300.0



def test_provider_error_fallback_is_not_counted_as_model_response():
    from scripts.benchmark_alberto import is_model_response

    assert is_model_response(
        "[sem modelo configurado pra task=chat: provider unavailable]",
        {"mode": "direct"},
    ) is False


def test_real_model_response_requires_strategy_and_no_error():
    from scripts.benchmark_alberto import is_model_response

    assert is_model_response("READY", {"mode": "direct"}) is True
    assert is_model_response("READY", {"mode": "direct"}, "provider timeout") is False
    assert is_model_response("READY", None) is False
