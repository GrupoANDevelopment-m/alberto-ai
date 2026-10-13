#!/usr/bin/env python3
"""Run a real, provider-backed Alberto AI quality/latency benchmark.

This script never substitutes mocked model responses. Each recorded response
comes from Alberto.chat; API failures are recorded as failures, not fabricated
outputs. It intentionally reports latency and task correctness only because
the current chat interface does not expose reliable token/cost usage.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


TASKS: List[Dict[str, Any]] = [
    {
        "id": "instruction_token",
        "category": "instruction_following",
        "prompt": "Responda exclusivamente com o token READY, sem aspas nem pontuação.",
        "scorer": "exact",
        "expected": "READY",
    },
    {
        "id": "arithmetic_17x6_minus19",
        "category": "arithmetic",
        "prompt": "Calcule (17 * 6) - 19. Responda apenas com o número inteiro.",
        "scorer": "exact",
        "expected": "83",
    },
    {
        "id": "json_status_count",
        "category": "structured_output",
        "prompt": "Responda somente com JSON válido, sem markdown, com status igual a ok e count igual a 3.",
        "scorer": "json_status_count",
        "expected": {"status": "ok", "count": 3},
    },
    {
        "id": "exact_three_lines",
        "category": "instruction_following",
        "prompt": "Escreva exatamente estas três linhas, sem texto adicional:\nITEM-1\nITEM-2\nITEM-3",
        "scorer": "exact_lines",
        "expected": ["ITEM-1", "ITEM-2", "ITEM-3"],
    },
    {
        "id": "sentiment_portuguese",
        "category": "classification_pt",
        "prompt": "Classifique a frase usando apenas uma palavra: POSITIVO, NEGATIVO ou NEUTRO. Frase: A equipa concluiu o projeto antes do prazo e o cliente elogiou o resultado.",
        "scorer": "exact",
        "expected": "POSITIVO",
    },
    {
        "id": "inventory_arithmetic",
        "category": "arithmetic",
        "prompt": "Uma equipa tem 4 caixas com 7 peças cada, perde 5 peças e recebe mais 9. Responda apenas com o total inteiro.",
        "scorer": "exact",
        "expected": "32",
    },
    {
        "id": "word_count_angola",
        "category": "language",
        "prompt": "Quantas letras tem a palavra Angola? Responda apenas com o número.",
        "scorer": "exact",
        "expected": "6",
    },
    {
        "id": "sort_numbers",
        "category": "instruction_following",
        "prompt": "Ordene os números 9, 2, 5 em ordem crescente. Responda apenas no formato 2,5,9.",
        "scorer": "exact",
        "expected": "2,5,9",
    },
    {
        "id": "english_token",
        "category": "multilingual",
        "prompt": "Reply with exactly this uppercase word and no punctuation: ACCEPTED",
        "scorer": "exact",
        "expected": "ACCEPTED",
    },
    {
        "id": "logical_condition",
        "category": "reasoning",
        "prompt": "If all A are B and no B are C, can any A be C? Answer only YES or NO.",
        "scorer": "exact",
        "expected": "NO",
    },
]


def _clean_exact(response: str) -> str:
    return response.strip().strip(chr(96)).strip()


def _parse_json_object(response: str) -> Dict[str, Any]:
    text = response.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        lines = text.splitlines()
        if lines and lines[0].startswith(fence):
            lines = lines[1:]
        if lines and lines[-1].strip() == fence:
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response contains no JSON object")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("response JSON is not an object")
    return parsed


def score_response(task: Dict[str, Any], response: str) -> bool:
    """Deterministic scoring for the small baseline suite; no evaluator model."""
    scorer = task["scorer"]
    expected = task["expected"]
    if scorer == "exact":
        return _clean_exact(response) == expected
    if scorer == "exact_lines":
        lines = [line.strip() for line in response.strip().splitlines() if line.strip()]
        return lines == expected
    if scorer == "json_status_count":
        try:
            parsed = _parse_json_object(response)
        except (ValueError, json.JSONDecodeError):
            return False
        return parsed.get("status") == expected["status"] and parsed.get("count") == expected["count"]
    raise ValueError(f"unknown scorer: {scorer}")


def _percentile(values: List[float], p: float):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return round(ordered[index], 2)


def summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(results)
    passed = sum(1 for result in results if result.get("passed") is True)
    latencies = [float(result["latency_ms"]) for result in results if result.get("latency_ms") is not None]
    errors = sum(1 for result in results if result.get("error"))
    return {
        "cases": count,
        "passed": passed,
        "pass_rate": round(passed / count, 4) if count else 0.0,
        "errors": errors,
        "error_rate": round(errors / count, 4) if count else 0.0,
        "mean_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "median_latency_ms": round(statistics.median(latencies), 2) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
    }


def run_benchmark(repeats: int = 1, pause_seconds: float = 0.25) -> Dict[str, Any]:
    """Run against the configured provider; all recorded responses are live."""
    from alberto import Alberto

    if repeats < 1 or repeats > 20:
        raise ValueError("repeats must be between 1 and 20")
    if pause_seconds < 0 or pause_seconds > 30:
        raise ValueError("pause must be between 0 and 30 seconds")

    agent = Alberto()
    results: List[Dict[str, Any]] = []
    try:
        configured_tasks = agent.router.list_tasks()
        if not configured_tasks:
            raise RuntimeError(
                "No model tasks are configured. Configure a provider/model first; "
                "the benchmark will not generate substitute responses."
            )

        for repeat in range(1, repeats + 1):
            for task in TASKS:
                conversation = agent.conversations.create()
                started = time.perf_counter()
                record: Dict[str, Any] = {
                    "task_id": task["id"],
                    "category": task["category"],
                    "repeat": repeat,
                    "prompt": task["prompt"],
                    "passed": False,
                    "latency_ms": None,
                    "tool_call_count": 0,
                    "error": None,
                }
                try:
                    result = agent.chat(task["prompt"], conversation_id=conversation.id)
                    latency_ms = (time.perf_counter() - started) * 1000
                    response = str(result.get("response", "") or "")
                    record.update({
                        "response": response,
                        "passed": score_response(task, response),
                        "latency_ms": round(latency_ms, 2),
                        "tool_call_count": len(result.get("tool_calls") or []),
                        "strategy": str(result.get("strategy") or "")[:200],
                    })
                except Exception as exc:
                    record["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                    record["error"] = f"{type(exc).__name__}: {exc}"
                results.append(record)
                if pause_seconds:
                    time.sleep(pause_seconds)

        return {
            "schema_version": 1,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "agent_version": getattr(agent, "version", "unknown"),
            "sandbox_type": type(agent.sandbox).__name__,
            "sandbox_isolation_level": getattr(agent.sandbox, "isolation_level", "host-process"),
            "configured_model_tasks": configured_tasks,
            "suite": "alberto-real-quality-latency-v1",
            "repeats": repeats,
            "metrics": summarize_results(results),
            "results": results,
            "notes": [
                "Responses are live outputs from Alberto.chat; no mock model responses are used.",
                "Scores are deterministic checks for instruction following, simple reasoning, and structured output.",
                "Token counts and cost are omitted because the current chat interface does not expose reliable usage metadata.",
                "Host-process sandbox modes do not provide OS-level isolation.",
            ],
        }
    finally:
        agent.shutdown()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=1, help="number of live runs per task (1-20)")
    parser.add_argument("--pause", type=float, default=0.25, help="seconds between provider calls")
    parser.add_argument("--output", type=Path, help="output JSON path; defaults to a timestamped file under benchmark-results/")
    args = parser.parse_args(argv)

    try:
        report = run_benchmark(repeats=args.repeats, pause_seconds=args.pause)
    except Exception as exc:
        print(f"Benchmark could not complete: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or Path("benchmark-results") / f"alberto-real-{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "metrics": report["metrics"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
