"""
Model router — generic, no hardcoded providers or models.

User configures model per task via:
    config set models.reasoning.provider "nvidia"
    config set models.reasoning.model_id "moonshotai/kimi-k2.6"
    config set models.reasoning.base_url "https://integrate.api.nvidia.com/v1"
    config set models.reasoning.credential_env "NVIDIA_API_KEY"

The router then resolves any task to the configured spec, or walks the
fallback chain when the primary fails.

Universal protocol: every provider is OpenAI-compatible
    POST {base_url}/v1/chat/completions
    Authorization: Bearer {credential_from_env}
"""

from __future__ import annotations
import json
import os
import urllib.request
import urllib.error
import ssl
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


@dataclass
class ModelSpec:
    """A single model configuration. Fully user-defined, no defaults."""
    provider: str            # user-chosen: "nvidia", "openai", "anthropic-via-gateway", "local-ollama", ...
    model_id: str            # user-chosen: "<provider>/<model>" or any string
    base_url: str            # OpenAI-compat base URL (no /v1 suffix; we add it)
    credential_env: str      # env var name to read the API key from
    options: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelSpec":
        return cls(
            provider=d["provider"],
            model_id=d["model_id"],
            base_url=d["base_url"],
            credential_env=d["credential_env"],
            options=d.get("options", {}) or {},
        )


@dataclass
class ModelConfig:
    """Per-task model configuration with fallback chain."""
    tasks: Dict[str, ModelSpec]                # task name -> spec
    fallback_chain: List[ModelSpec] = field(default_factory=list)

    def resolve(self, task: str) -> Optional[ModelSpec]:
        """Return primary spec for task, or None if not configured."""
        return self.tasks.get(task)

    def resolve_with_fallback(self, task: str) -> List[ModelSpec]:
        """Return [primary, fallback1, fallback2, ...]. Empty list if nothing configured."""
        primary = self.resolve(task)
        chain: List[ModelSpec] = []
        if primary is not None:
            chain.append(primary)
        chain.extend(self.fallback_chain)
        return chain

    def set_task(self, task, spec):
        self.tasks[task] = spec

    def add_fallback(self, spec):
        self.fallback_chain.append(spec)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "fallback_chain": [s.to_dict() for s in self.fallback_chain],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelConfig":
        tasks = {k: ModelSpec.from_dict(v) for k, v in d.get("tasks", {}).items()}
        chain = [ModelSpec.from_dict(s) for s in d.get("fallback_chain", [])]
        return cls(tasks=tasks, fallback_chain=chain)


class ModelRouter:
    """Resolves task -> ModelSpec and sends OpenAI-compat requests."""

    def __init__(self, config: ModelConfig):
        self._config = config

    @property
    def config(self) -> ModelConfig:
        return self._config

    def set_task(self, task: str, spec: ModelSpec) -> None:
        self._config.tasks[task] = spec

    def add_fallback(self, spec: ModelSpec) -> None:
        self._config.fallback_chain.append(spec)

    def list_tasks(self) -> List[str]:
        return sorted(self._config.tasks.keys())

    def resolve(self, task: str) -> Optional[ModelSpec]:
        return self._config.resolve(task)

    def _get_credential(self, spec: ModelSpec) -> Optional[str]:
        return os.environ.get(spec.credential_env)

    def _make_payload(self, spec: ModelSpec, messages: List[Dict[str, str]],
                      *, stream: bool, max_tokens: int = 4096,
                      temperature: float = 1.0) -> Dict[str, Any]:
        payload = {
            "model": spec.model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        # Merge user options (e.g. chat_template_kwargs for thinking models)
        payload.update(spec.options)
        return payload

    def _build_request(self, spec: ModelSpec, payload: Dict[str, Any]) -> urllib.request.Request:
        # Strip trailing /v1 to avoid doubling up
        base = spec.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        url = base + "/v1/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        cred = self._get_credential(spec) or ""
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cred}",
                "Accept": "text/event-stream" if payload.get("stream") else "application/json",
            },
            method="POST",
        )
        return req

    def invoke(self, task: str, messages: List[Dict[str, str]],
               *, stream: bool = False, max_tokens: int = 4096,
               temperature: float = 1.0, tools: Optional[List[Dict]] = None,
               tool_choice: Optional[str] = None) -> Dict[str, Any]:
        """Call the resolved model. Returns the parsed JSON response.

        Walks the fallback chain automatically on error.

        Args:
            tools: OpenAI-compat tool definitions to pass to the model
            tool_choice: "auto" | "required" | "none" | specific function name
        """
        chain = self._config.resolve_with_fallback(task)
        if not chain:
            raise RuntimeError(
                f"No model configured for task '{task}'. "
                f"Run: alberto model set {task} <provider> <model_id> <base_url> <credential_env>"
            )

        last_err: Optional[Exception] = None
        for i, spec in enumerate(chain):
            if not self._get_credential(spec):
                last_err = RuntimeError(f"credential env {spec.credential_env!r} is not set")
                continue
            payload = self._make_payload(spec, messages, stream=False,
                                         max_tokens=max_tokens, temperature=temperature)
            if tools:
                payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
            req = self._build_request(spec, payload)
            try:
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                last_err = RuntimeError(f"{spec.provider}/{spec.model_id} -> HTTP {e.code}: {body[:200]}")
            except Exception as e:
                last_err = RuntimeError(f"{spec.provider}/{spec.model_id} -> {e}")
        raise RuntimeError(f"all {len(chain)} model(s) failed for task '{task}': {last_err}")

    def render_env(self, task: str) -> Dict[str, str]:
        """Show what env vars would be passed to the engine (for /model test)."""
        spec = self._config.resolve(task)
        if spec is None:
            return {}
        cred = self._get_credential(spec) or ""
        return {
            "OPENAI_BASE_URL": spec.base_url,
            "OPENAI_API_KEY": cred,
            "LLM_MODEL": spec.model_id,
            "ALBERTO_PROVIDER": spec.provider,
            "ALBERTO_OPTIONS_JSON": json.dumps(spec.options),
        }