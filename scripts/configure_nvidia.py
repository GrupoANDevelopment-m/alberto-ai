#!/usr/bin/env python3
"""Write NVIDIA model routing configuration without storing API key values."""
from __future__ import annotations
import json
import os
from pathlib import Path

home = Path(os.environ.get(
    "ALBERTO_SANDBOX_DIR",
    str(Path.home() / ".local" / "share" / "alberto-ai" / "sandbox"),
)).expanduser()
path = home / "home" / ".mimo" / "model_config.json"
path.parent.mkdir(parents=True, exist_ok=True)

primary = {
    "provider": "nvidia",
    "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
    "base_url": "https://integrate.api.nvidia.com/v1",
    "credential_env": "NVIDIA_API_KEY",
    "options": {"chat_template_kwargs": {"thinking": True}, "reasoning_budget": 16384},
}
fallback = {
    "provider": "nvidia",
    "model_id": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "base_url": "https://integrate.api.nvidia.com/v1",
    "credential_env": "NVIDIA_API_KEY_FALLBACK",
    "options": {},
}
config = {
    "tasks": {task: dict(primary) for task in ("chat", "reasoning", "code")},
    "fallback_chain": [fallback],
}
if path.exists():
    backup = path.with_suffix(".json.backup")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Previous config backed up to: {backup}")
path.write_text(json.dumps(config, indent=2), encoding="utf-8")
print(f"NVIDIA routing config written: {path}")
print("No API key values were written. Export NVIDIA_API_KEY and NVIDIA_API_KEY_FALLBACK in your shell.")
