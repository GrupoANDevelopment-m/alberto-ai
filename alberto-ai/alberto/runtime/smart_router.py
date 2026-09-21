"""Smart LLM Router — like OmniRoute, but for Alberto.

Routes LLM calls across multiple providers/models based on:
- Cost per token
- Latency target
- Model capability (chat/code/reasoning/vision)
- Current rate limit status
- Past success/failure

When one provider fails, falls back to the next best option.
Tracks per-model stats: cost, latency, success rate.

Usage:
  alberto.smart_router.complete(messages, task="code", max_tokens=2000)
  alberto.smart_router.get_stats()
"""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ModelSpec:
    """One LLM endpoint spec."""
    provider: str
    model_id: str
    base_url: str
    credential_env: str
    cost_per_1k_input: float = 0.0  # USD per 1k input tokens
    cost_per_1k_output: float = 0.0
    capability: str = "chat"  # chat|code|reasoning|vision
    priority: int = 50  # higher = preferred
    enabled: bool = True


@dataclass
class ModelStats:
    """Per-model statistics."""
    calls: int = 0
    successes: int = 0
    failures: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    last_used: float = 0.0
    last_error: str = ""


class SmartRouter:
    """Multi-model LLM router with cost + latency optimization."""

    def __init__(self, alberto):
        self.alberto = alberto
        self.specs: List[ModelSpec] = []
        self.stats: Dict[str, ModelStats] = {}  # model_id -> stats
        self._stats_path = alberto.sandbox.home() / ".mimo" / "router_stats.json"
        self._load_stats()
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self._load_specs_from_alberto()
            self._loaded = True

    def _load_specs_from_alberto(self):
        """Build specs from Alberto's existing model_router configuration."""
        models = {}
        try:
            config = self.alberto.router.config
            for task, spec in config.tasks.items():
                models[task] = {
                    "provider": spec.provider,
                    "model_id": spec.model_id,
                    "base_url": spec.base_url,
                    "credential_env": spec.credential_env,
                }
            for spec in config.fallback_chain:
                models.setdefault("fallback", {
                    "provider": spec.provider,
                    "model_id": spec.model_id,
                    "base_url": spec.base_url,
                    "credential_env": spec.credential_env,
                })
        except Exception as e:
            print(f"smart_router load: {e}")
        for task, m in (models or {}).items():
            spec = ModelSpec(
                provider=m.get("provider", ""),
                model_id=m.get("model_id", ""),
                base_url=m.get("base_url", ""),
                credential_env=m.get("credential_env", "NVIDIA_API_KEY"),
                capability=task,
            )
            # Heuristic pricing (USD per 1k tokens)
            mid = spec.model_id.lower()
            if "diffusiongemma" in mid:
                spec.cost_per_1k_input = 0.0001
                spec.cost_per_1k_output = 0.0001
            elif "glm" in mid or "minimax" in mid:
                spec.cost_per_1k_input = 0.001
                spec.cost_per_1k_output = 0.001
            elif "gpt-4" in mid:
                spec.cost_per_1k_input = 0.03
                spec.cost_per_1k_output = 0.06
            elif "claude" in mid:
                spec.cost_per_1k_input = 0.008
                spec.cost_per_1k_output = 0.024
            self.specs.append(spec)
            self.stats.setdefault(spec.model_id, ModelStats())

    def _load_stats(self):
        if self._stats_path.exists():
            try:
                data = json.loads(self._stats_path.read_text())
                for mid, s in data.items():
                    self.stats[mid] = ModelStats(**s)
            except Exception:
                pass
        else:
            self._stats_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_stats()

    def _save_stats(self):
        data = {mid: vars(s) for mid, s in self.stats.items()}
        self._stats_path.write_text(json.dumps(data, indent=2, default=str))

    def add_spec(self, spec: ModelSpec):
        self.specs.append(spec)
        self.stats.setdefault(spec.model_id, ModelStats())

    def rank_models(self, task: str = "chat", *,
                   prefer_cheap: bool = False,
                   exclude_failed_recently: bool = True) -> List[ModelSpec]:
        self._ensure_loaded()
        """Return specs ranked by suitability for the task."""
        candidates = [s for s in self.specs if s.enabled and s.capability == task]
        if not candidates:
            candidates = [s for s in self.specs if s.enabled]
        # Filter out recently-failed
        if exclude_failed_recently:
            _ = 0  # placeholder
            # Original logic follows
            now = time.time()
            candidates = [s for s in candidates
                         if not (self.stats.get(s.model_id, ModelStats()).last_error
                                 and now - self.stats[s.model_id].last_used < 60)]
        # Score: higher priority + lower cost (if prefer_cheap) + higher success rate
        def score(s: ModelSpec) -> float:
            stats = self.stats.get(s.model_id, ModelStats())
            success_rate = (stats.successes / max(stats.calls, 1))
            avg_latency = stats.avg_latency_ms / 1000.0  # to seconds
            sc = s.priority * 0.5 + success_rate * 100 * 0.3
            if prefer_cheap:
                sc -= (s.cost_per_1k_input + s.cost_per_1k_output) * 1000
            if avg_latency > 0:
                sc -= avg_latency * 5  # penalize slow models
            return sc
        candidates.sort(key=score, reverse=True)
        return candidates

    def complete(self, messages: List[Dict[str, str]], *,
                 task: str = "chat", max_tokens: int = 1024,
                 temperature: float = 1.0, stream: bool = False,
                 prefer_cheap: bool = False) -> Dict[str, Any]:
        """Try to complete via the best model, with automatic fallback."""
        self._ensure_loaded()
        candidates = self.rank_models(task, prefer_cheap=prefer_cheap)
        if not candidates:
            return {"ok": False, "error": "no models available"}
        last_err = None
        for spec in candidates:
            t0 = time.time()
            try:
                result = self._call(spec, messages, max_tokens, temperature, stream)
                elapsed_ms = (time.time() - t0) * 1000
                self._record_success(spec, result, elapsed_ms)
                result["model_used"] = spec.model_id
                result["provider"] = spec.provider
                return result
            except Exception as e:
                elapsed_ms = (time.time() - t0) * 1000
                self._record_failure(spec, str(e), elapsed_ms)
                last_err = e
                continue
        return {"ok": False, "error": f"all {len(candidates)} models failed: {last_err}"}

    def _call(self, spec: ModelSpec, messages: List[Dict], max_tokens: int,
             temperature: float, stream: bool) -> Dict[str, Any]:
        """Call a model via OpenAI-compat HTTP API."""
        import os
        api_key = os.environ.get(spec.credential_env, "")
        if not api_key:
            raise RuntimeError(f"missing credential {spec.credential_env}")
        # Strip /v1 if already in base_url (some providers include it)
        base = spec.base_url.rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        url = f"{base}/v1/chat/completions"
        data = json.dumps({
            "model": spec.model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read())
        choice = body.get("choices", [{}])[0]
        usage = body.get("usage", {})
        return {
            "ok": True,
            "content": choice.get("message", {}).get("content", ""),
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }

    def _record_success(self, spec: ModelSpec, result: Dict, elapsed_ms: float):
        s = self.stats.setdefault(spec.model_id, ModelStats())
        s.calls += 1
        s.successes += 1
        s.total_input_tokens += result.get("input_tokens", 0)
        s.total_output_tokens += result.get("output_tokens", 0)
        cost_in = (result.get("input_tokens", 0) / 1000) * spec.cost_per_1k_input
        cost_out = (result.get("output_tokens", 0) / 1000) * spec.cost_per_1k_output
        s.total_cost_usd += cost_in + cost_out
        s.avg_latency_ms = ((s.avg_latency_ms * (s.calls - 1)) + elapsed_ms) / s.calls
        s.last_used = time.time()
        self._save_stats()

    def _record_failure(self, spec: ModelSpec, error: str, elapsed_ms: float):
        s = self.stats.setdefault(spec.model_id, ModelStats())
        s.calls += 1
        s.failures += 1
        s.avg_latency_ms = ((s.avg_latency_ms * (s.calls - 1)) + elapsed_ms) / s.calls
        s.last_used = time.time()
        s.last_error = error
        self._save_stats()

    def get_stats(self) -> Dict[str, Any]:
        """Get all model stats."""
        return {mid: vars(s) for mid, s in self.stats.items()}

    def total_cost(self) -> float:
        return sum(s.total_cost_usd for s in self.stats.values())


def main(argv):
    import argparse
    p = argparse.ArgumentParser(prog="alberto router")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("stats")
    sub.add_parser("cost")
    sub.add_parser("rank")
    args = p.parse_args(argv)
    from alberto import Alberto
    a = Alberto()
    r = SmartRouter(a)
    if args.cmd == "list":
        for s in r.specs:
            print(f"  [{s.capability:10s}] {s.provider:10s} {s.model_id:35s} cost_in=${s.cost_per_1k_input:.4f}/1k")
    elif args.cmd == "stats":
        for mid, s in r.stats.items():
            print(f"  {mid:35s} calls={s.calls} ok={s.successes} fail={s.failures} cost=${s.total_cost_usd:.4f} avg_lat={s.avg_latency_ms:.0f}ms")
    elif args.cmd == "cost":
        print(f"Total cost: ${r.total_cost():.4f}")
    elif args.cmd == "rank":
        for s in r.rank_models("chat", prefer_cheap=False):
            print(f"  {s.model_id:35s} priority={s.priority}")
    a.shutdown()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
