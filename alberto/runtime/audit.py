"""audit.py - Audit log for all tool calls (v1.7).

Records every tool invocation (and shell execution) to a persistent log so
the user can audit what Alberto's LLM did on their machine.
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


AUDIT_PATH = Path.home() / ".alberto" / "audit.log"


def _ensure_audit_path() -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_event(event_type: str, details: dict) -> None:
    """Persist a structured audit event."""
    try:
        _ensure_audit_path()
        entry = {
            "ts": datetime.now().isoformat(),
            "pid": os.getpid(),
            "type": event_type,
            **details,
        }
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def log_tool_call(tool_name: str, args: dict, result: Any,
                  user_confirmed: bool = False) -> None:
    """Log a tool call from the LLM."""
    safe_args = {}
    for k, v in args.items():
        if k in ("content", "value", "command", "code", "prompt"):
            if isinstance(v, str):
                safe_args[k] = v[:200] + ("..." if len(v) > 200 else "")
            else:
                safe_args[k] = v
        else:
            safe_args[k] = v
    log_event("tool_call", {
        "tool": tool_name,
        "args": safe_args,
        "result_is_err": bool(result[1] if isinstance(result, tuple) else False),
        "user_confirmed": user_confirmed,
    })


def log_blocked_shell(command: str, pattern_matched: str) -> None:
    log_event("blocked_shell", {
        "command": command[:200],
        "pattern": pattern_matched,
    })


def log_auto_exec(cmd: str, rc: int) -> None:
    log_event("auto_exec", {
        "cmd": cmd[:500],
        "rc": rc,
    })


def get_recent_events(n: int = 50) -> list:
    if not AUDIT_PATH.exists():
        return []
    events = []
    with AUDIT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
    return events[-n:]


def clear_audit_log() -> int:
    if not AUDIT_PATH.exists():
        return 0
    count = 0
    with AUDIT_PATH.open("r", encoding="utf-8") as f:
        for _ in f:
            count += 1
    AUDIT_PATH.unlink()
    return count
