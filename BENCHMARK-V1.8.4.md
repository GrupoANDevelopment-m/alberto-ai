# Alberto AI v1.8.4 — Real Provider Benchmark

Executed with `scripts/benchmark_alberto.py` (real provider calls, **no mocks**).
Script came from `audit/real-benchmark` branch.

## Configuration

| Item | Value |
|---|---|
| Agent version | 1.0.0 |
| Primary model | `nvidia/nemotron-3-ultra-550b-a55b` |
| Fallback | `nvidia/nemotron-3.5-lightning-30b-a3b` (thinking enabled) |
| Tasks configured | chat, code, embed, reasoning, summary, vision |
| Sandbox | LocalSandbox (host-process) |
| Repeats | 1 per case |

## Results — 10/10 passed (100%)

| Metric | Value |
|---|---|
| Cases | 10 |
| Passed | **10 (100%)** |
| Errors | 0 |
| Mean latency | 13,477 ms |
| Median latency | 13,096 ms |
| p95 latency | 16,590 ms |

### By category

| Category | Cases | Pass rate | Median latency |
|---|---|---|---|
| arithmetic | 2 | 100% | 14,677 ms |
| classification_pt | 1 | 100% | 13,785 ms |
| instruction_following | 3 | 100% | 12,439 ms |
| language | 1 | 100% | 13,386 ms |
| multilingual | 1 | 100% | 12,938 ms |
| reasoning | 1 | 100% | 14,606 ms |
| structured_output | 1 | 100% | 12,890 ms |

All cases answered in pt-BR and en as required, including strict-format
(JSON-only, exact-string) and multi-step arithmetic.

## Latency context (honest comparison)

The 13.1 s median reflects **nemotron-3-ultra-550b with reasoning enabled** —
a 550B model doing step-by-step thinking. Published framework benchmarks use
much smaller non-thinking models:

| Framework (agentmail 90-test suite) | Median |
|---|---|
| Mastra | 2.2 s |
| Pydantic AI | 2.2 s |
| LangGraph | 2.5 s |
| OpenAI Agents SDK | 2.5 s |
| AG2 | 2.8 s |
| Google ADK | 3.4 s |
| CrewAI | 4.0 s |
| Claude Agent SDK | 8.5 s |
| **Alberto (nemotron-3-ultra, thinking)** | **13.1 s** |

To compare apples-to-apples, re-run with a small non-thinking model
(e.g. `meta/llama-3.1-8b-instruct`) — that isolates framework overhead from
model latency.

## Reproduce

```bash
export NVIDIA_API_KEY=...
export NVIDIA_API_KEY_FALLBACK=...
alberto model set chat nvidia nvidia/nemotron-3-ultra-550b-a55b \
  https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY
python scripts/benchmark_alberto.py --repeats 3 --pause 2
```

Raw result: `benchmark-results/latest-real-benchmark.json`
