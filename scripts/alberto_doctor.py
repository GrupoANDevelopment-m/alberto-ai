#!/usr/bin/env python3
"""Read-only local installation and skill-catalog diagnostic."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "skills"
HERMES = ROOT / "upstream" / "hermes" / "skills"
default_home = Path.home() / ".local" / "share" / "alberto-ai" / "sandbox"
sandbox = Path(os.environ.get("ALBERTO_SANDBOX_DIR", str(default_home))).expanduser()
config_path = sandbox / "home" / ".mimo" / "model_config.json"

def count_skills(path: Path) -> int:
    return sum(1 for _ in path.rglob("SKILL.md")) if path.is_dir() else 0

local_count = count_skills(LOCAL)
hermes_count = count_skills(HERMES)
print("ALBERTO AI LOCAL DIAGNOSTIC")
print(f"Repository: {ROOT}")
print(f"Python: {sys.version.split()[0]}")
print(f"Python executable: {sys.executable}")
print(f"Local skills directory: {LOCAL} ({local_count} SKILL.md)")
print(f"Hermes upstream skills: {HERMES} ({hermes_count} SKILL.md)")
print(f"Total skill definition files: {local_count + hermes_count}")
print(f"Sandbox home: {sandbox}")
print(f"Model config: {config_path}")

errors = []
if sys.version_info < (3, 11):
    errors.append("Python 3.11+ is required.")
for name, path in (("skills/", LOCAL), ("upstream/hermes/skills/", HERMES)):
    if not path.is_dir():
        errors.append(f"Missing required directory: {name}")

try:
    from alberto.upstream_bridge import list_upstream_skills
    discovered = list_upstream_skills()
    print(f"Skills discoverable by Alberto runtime: {len(discovered)}")
    if not discovered:
        errors.append("Runtime discovered zero skills.")
except Exception as exc:
    print(f"Runtime skill discovery: FAILED ({type(exc).__name__}: {exc})")
    errors.append("Could not import the runtime skill catalog.")

if config_path.exists():
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        tasks = cfg.get("tasks", {})
        print("Configured model tasks:", ", ".join(sorted(tasks)) or "(none)")
        print("Fallback models:", len(cfg.get("fallback_chain", [])))
        for task in ("chat", "reasoning", "code"):
            spec = tasks.get(task)
            if spec:
                env_name = spec.get("credential_env", "")
                print(f"  {task}: {spec.get('provider')}/{spec.get('model_id')} | credential env={env_name} | key present={'yes' if os.environ.get(env_name) else 'no'}")
    except Exception as exc:
        errors.append(f"Model config is not valid JSON/schema: {exc}")
else:
    print("Model configuration: NOT CONFIGURED")

if errors:
    print("\nDIAGNOSTIC: NEEDS ATTENTION")
    for item in errors:
        print(" -", item)
    raise SystemExit(1)
print("\nDIAGNOSTIC: STRUCTURE OK")
