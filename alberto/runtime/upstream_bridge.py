"""upstream_bridge.py - Real integration with upstream Hermes tools.

Loads the FULL production Hermes tool registry via model_tools.py and
provides real_* functions that call the actual upstream code.

Hermes has 87 production tools in upstream/hermes/tools/. This bridge
loads them via the model_tools registry and exposes them through 25+
real_* functions.

Usage:
    from alberto.runtime.upstream_bridge import (
        handle_hermes_tool_call, real_browser_navigate,
        real_browser_click, real_execute_code, real_memory_save,
        real_terminal_run, real_write_file, ...
    )

    # Direct call
    result = handle_hermes_tool_call("browser_navigate", {"url": "https://..."})

    # Via OpenAI tool calling
    tool_defs = get_openai_tool_definitions()
"""
from __future__ import annotations
import os
import sys
import json
import subprocess
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Add upstream paths
UPSTREAM_ROOT = Path(__file__).parent.parent.parent / "upstream"
HERMES_PY = UPSTREAM_ROOT / "hermes"

# Ensure upstream path is importable
if str(HERMES_PY) not in sys.path:
    sys.path.insert(0, str(HERMES_PY))


_LOADED = False
_MODEL_TOOLS = None
_BRIDGE_FUNCS = {}


def _ensure_loaded() -> bool:
    """Lazy-load model_tools + discover all Hermes tools."""
    global _LOADED, _MODEL_TOOLS
    if _LOADED:
        return True
    try:
        import model_tools
        _MODEL_TOOLS = model_tools
        _LOADED = True
        return True
    except Exception as e:
        sys.stderr.write(f"[upstream_bridge] failed to load model_tools: {e}\n")
        return False


# ===================== Tool dispatch =====================

# Agent-loop tools (intercepted by Hermes run_agent.py, must handle here)
_AGENT_LOOP_TOOLS = {"memory", "todo", "session_search", "delegate_task"}


def handle_hermes_tool_call(function_name: str, function_args: Dict[str, Any],
                              **kwargs) -> str:
    """Dispatch a tool call to the real Hermes tool.

    This is the bridge to the real Hermes model_tools.handle_function_call().
    For agent-loop tools (memory, todo, session_search), uses our own
    real_* functions (sqlite-backed) since Hermes intercepts those in
    run_agent.py.

    Args: function_name (str), function_args (dict), task_id (str, optional).
    Returns: JSON string result.
    """
    if not _ensure_loaded():
        return json.dumps({"error": "upstream not loaded"})
    # Agent-loop tools: handle via our own sqlite impl
    if function_name == "memory":
        action = function_args.get("action", "get")
        if action == "set":
            real_memory_set(function_args.get("key", ""), function_args.get("value", ""))
            return json.dumps({"ok": True, "key": function_args.get("key")})
        elif action == "get":
            val, _ = real_memory_get(function_args.get("key", ""))
            return json.dumps({"key": function_args.get("key"), "value": val or ""})
        elif action == "search":
            results, _ = real_memory_search(function_args.get("query", ""), limit=function_args.get("limit", 5))
            return json.dumps({"results": results})
        elif action == "list":
            db = Path.home() / ".hermes" / "memory.db"
            if not db.exists():
                return json.dumps({"keys": []})
            import sqlite3
            conn = sqlite3.connect(str(db))
            rows = conn.execute("SELECT key FROM memory").fetchall()
            conn.close()
            return json.dumps({"keys": [r[0] for r in rows]})
    if function_name == "session_search":
        # Treat as memory search
        results, _ = real_memory_search(function_args.get("query", ""), limit=function_args.get("limit", 5))
        return json.dumps({"sessions": results, "matches": results})
    try:
        # Use real Hermes handle_function_call
        return _MODEL_TOOLS.handle_function_call(function_name, function_args, **kwargs)
    except Exception as e:
        return json.dumps({"error": f"{function_name}: {e}"})


def get_openai_tool_definitions() -> List[Dict[str, Any]]:
    """Get OpenAI-compat tool definitions from real Hermes model_tools."""
    if not _ensure_loaded():
        return []
    try:
        return _MODEL_TOOLS.get_tool_definitions()
    except Exception as e:
        sys.stderr.write(f"[upstream_bridge] get_tool_definitions failed: {e}\n")
        return []


# ===================== Direct tool accessors =====================

def _call(name: str, args: Dict, **kwargs) -> Tuple[str, bool]:
    """Generic call to a Hermes tool."""
    try:
        result = handle_hermes_tool_call(name, args, **kwargs)
        if result is None:
            return f"no result from {name}", True
        if isinstance(result, str) and result.startswith('{"error"'):
            return result, True
        # Check JSON for error/exit_code fields
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    if parsed.get("error"):
                        return result, True
                    if parsed.get("exit_code") and parsed["exit_code"] != 0:
                        return result, True
            except (json.JSONDecodeError, ValueError):
                pass
        return result, False
    except Exception as e:
        return f"error: {e}", True


# ===================== Real wrapper functions =====================

def real_browser_navigate(url: str, **kwargs) -> Tuple[str, bool]:
    """Navigate to URL in real Hermes browser."""
    return _call("browser_navigate", {"url": url}, **kwargs)


def real_browser_click(ref: str, **kwargs) -> Tuple[str, bool]:
    """Click element by ref."""
    return _call("browser_click", {"ref": ref}, **kwargs)


def real_browser_type(ref: str, text: str, **kwargs) -> Tuple[str, bool]:
    """Type text into element."""
    return _call("browser_type", {"ref": ref, "text": text}, **kwargs)


def real_browser_snapshot(**kwargs) -> Tuple[str, bool]:
    """Get accessibility snapshot."""
    return _call("browser_snapshot", {}, **kwargs)


def real_browser_scroll(direction: str, **kwargs) -> Tuple[str, bool]:
    """Scroll up/down."""
    return _call("browser_scroll", {"direction": direction}, **kwargs)


def real_browser_press(key: str, **kwargs) -> Tuple[str, bool]:
    """Press a key."""
    return _call("browser_press", {"key": key}, **kwargs)


def real_browser_console(**kwargs) -> Tuple[str, bool]:
    """Get browser console."""
    return _call("browser_console", {}, **kwargs)


def real_terminal_run(command: str, **kwargs) -> Tuple[str, bool]:
    """Run shell command."""
    return _call("terminal", {"command": command}, **kwargs)


def real_execute_code(code: str, **kwargs) -> Tuple[str, bool]:
    """Run Python script with tool access (Hermes PTC)."""
    return _call("execute_code", {"code": code}, **kwargs)


def real_read_file(path: str, start_line: int = 0, max_lines: int = 200, **kwargs) -> Tuple[str, bool]:
    """Read file with line numbers."""
    return _call("read_file", {"path": path, "start_line": start_line, "max_lines": max_lines}, **kwargs)


def real_write_file(path: str, content: str, **kwargs) -> Tuple[str, bool]:
    """Write content to file."""
    return _call("write_file", {"path": path, "content": content}, **kwargs)


def real_patch_file(path: str, old_string: str, new_string: str, **kwargs) -> Tuple[str, bool]:
    """Find-and-replace edit."""
    return _call("patch", {"path": path, "old_string": old_string, "new_string": new_string}, **kwargs)


def real_search_files(pattern: str, path: str = ".", **kwargs) -> Tuple[str, bool]:
    """Search files by content."""
    return _call("search_files", {"pattern": pattern, "path": path}, **kwargs)


def real_memory(action: str, key: str = "", value: str = "", **kwargs) -> Tuple[str, bool]:
    """Save/retrieve memory."""
    return _call("memory", {"action": action, "key": key, "value": value}, **kwargs)


def real_todo(action: str, todos: List[Dict] = None, **kwargs) -> Tuple[str, bool]:
    """Manage todo list."""
    return _call("todo", {"action": action, "todos": todos or []}, **kwargs)


def real_skills_list(**kwargs) -> Tuple[str, bool]:
    """List available skills."""
    return _call("skills_list", {}, **kwargs)


def real_skill_view(name: str, **kwargs) -> Tuple[str, bool]:
    """View a skill's content."""
    return _call("skill_view", {"name": name}, **kwargs)


def real_skill_manage(action: str, name: str = "", content: str = "", **kwargs) -> Tuple[str, bool]:
    """Manage skills."""
    return _call("skill_manage", {"action": action, "name": name, "content": content}, **kwargs)


def real_clarify(question: str, options: List[str] = None, **kwargs) -> Tuple[str, bool]:
    """Ask user for clarification (real Hermes clarify)."""
    return _call("clarify", {"question": question, "options": options or []}, **kwargs)


def real_process(action: str, process_id: str = "", **kwargs) -> Tuple[str, bool]:
    """Manage background processes."""
    return _call("process", {"action": action, "process_id": process_id}, **kwargs)


def real_project_create(name: str, **kwargs) -> Tuple[str, bool]:
    """Create a desktop project."""
    return _call("project_create", {"name": name}, **kwargs)


def real_project_list(**kwargs) -> Tuple[str, bool]:
    """List desktop projects."""
    return _call("project_list", {}, **kwargs)


def real_project_switch(name: str, **kwargs) -> Tuple[str, bool]:
    """Switch to a project."""
    return _call("project_switch", {"name": name}, **kwargs)


# ===================== Memory (sqlite + FTS5) - kept from v1.8.2 =====================

def real_memory_set(key: str, value: str, tags: Optional[str] = None) -> Tuple[str, bool]:
    """Real memory_set (uses Hermes memory_tool if loaded, else sqlite)."""
    if _ensure_loaded():
        result, err = _call("memory", {"action": "set", "key": key, "value": value})
        if not err:
            return f"saved {key} (hermes)", False
    # SQLite fallback
    db = Path.home() / ".hermes" / "memory.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3
    import time as _time
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE IF NOT EXISTS memory (
        key TEXT PRIMARY KEY, value TEXT, tags TEXT, updated_at REAL
    )""")
    conn.execute("INSERT OR REPLACE INTO memory VALUES (?, ?, ?, ?)",
                 (key, value, tags or "", _time.time()))
    conn.commit()
    conn.close()
    return f"saved {key} (sqlite)", False


def real_memory_get(key: str) -> Tuple[Optional[str], bool]:
    """Real memory_get - direct sqlite (avoids Hermes memory_tool hang)."""
    db = Path.home() / ".hermes" / "memory.db"
    if not db.exists():
        return None, True
    import sqlite3
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
    conn.close()
    if row:
        return row[0], False
    return None, True


def real_memory_search(query: str, limit: int = 5) -> Tuple[List[Dict], bool]:
    """Real memory_search using FTS5."""
    db = Path.home() / ".hermes" / "memory.db"
    if not db.exists():
        return [], False
    import sqlite3
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
            USING fts5(key, value, tags, content='memory')""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory BEGIN
            INSERT INTO memory_fts(rowid, key, value, tags) VALUES (new.rowid, new.key, new.value, new.tags);
        END""")
        conn.commit()
        try:
            rows = conn.execute(
                "SELECT key, value FROM memory_fts WHERE memory_fts MATCH ? LIMIT ?",
                (query, limit)
            ).fetchall()
        except Exception:
            rows = []
        if not rows:
            rows = conn.execute(
                "SELECT key, value FROM memory WHERE value LIKE ? LIMIT ?",
                (f"%{query}%", limit)
            ).fetchall()
        conn.close()
        return [{"key": r[0], "value": r[1]} for r in rows], False
    except Exception:
        return [], True


# ===================== Other upstream tools (kept from v1.8.2) =====================

def _get(name: str) -> Optional[Any]:
    """Get a loaded upstream module (legacy compat)."""
    if not _ensure_loaded():
        return None
    try:
        return importlib.import_module(f"tools.{name}")
    except Exception:
        return None


def real_session_search(query: str, limit: int = 5) -> Tuple[str, bool]:
    """Search past sessions."""
    return _call("session_search", {"query": query, "limit": limit})


def real_osv_check(package: str, version: str = "") -> Tuple[str, bool]:
    """Check npm/PyPI package for malware."""
    mod = _get("osv_check")
    if mod and hasattr(mod, "check_package_for_malware"):
        try:
            return mod.check_package_for_malware(package, version), False
        except Exception as e:
            return f"osv_check failed: {e}", True
    return "osv_check module not available", True


def real_threat_patterns(text: str) -> Tuple[List[str], bool]:
    """Detect threats in text."""
    mod = _get("threat_patterns")
    if mod and hasattr(mod, "scan_for_threats"):
        try:
            return mod.scan_for_threats(text), False
        except Exception as e:
            return [f"error: {e}"], True
    return [], True


def real_path_security(path: str) -> Tuple[bool, str, bool]:
    """Check path traversal."""
    mod = _get("path_security")
    if mod and hasattr(mod, "has_traversal_component"):
        try:
            safe = not mod.has_traversal_component(path)
            return safe, "ok" if safe else "traversal detected", not safe
        except Exception as e:
            return True, f"check failed: {e}", True
    return True, "no check", False


def real_tirith_security(command: str) -> Tuple[bool, str, bool]:
    """Check shell command safety."""
    mod = _get("tirith_security")
    if mod and hasattr(mod, "check_command_security"):
        try:
            result = mod.check_command_security(command)
            if isinstance(result, dict):
                safe = result.get("safe", result.get("ok", True))
                reason = result.get("reason", result.get("message", str(result)))
                return safe, reason, not safe
            return bool(result), str(result), False
        except Exception as e:
            return True, f"check failed: {e}", True
    return True, "no check", False


def real_website_policy(url: str) -> Tuple[bool, str, bool]:
    """Check URL safety."""
    mod = _get("website_policy")
    if mod and hasattr(mod, "check_url_safety"):
        try:
            safe, reason = mod.check_url_safety(url)
            return safe, reason, not safe
        except Exception as e:
            return True, f"check failed: {e}", True
    return True, "no check", False


def real_fuzzy_match(text: str, patterns: List[str]) -> Tuple[List[str], bool]:
    """Fuzzy match."""
    mod = _get("fuzzy_match")
    if mod and hasattr(mod, "fuzzy_find_and_replace"):
        try:
            new_content, count, error, hint = mod.fuzzy_find_and_replace(
                content=patterns[0] if patterns else "",
                old_string=text,
                new_string="",
                replace_all=False
            )
            if error:
                return [error], True
            return [f"matched {count} times"], False
        except Exception as e:
            return [f"error: {e}"], True
    return ["fuzzy_match: no usable function"], True


def real_extract_document(path: str) -> Tuple[str, bool]:
    """Extract text from document."""
    mod = _get("read_extract")
    if mod and hasattr(mod, "extract_document_text"):
        try:
            return mod.extract_document_text(path), False
        except Exception as e:
            return f"extract failed: {e}", True
    return "read_extract not available", True


def real_budget_config(context_window: int) -> Tuple[str, bool]:
    """Token budget for context."""
    mod = _get("budget_config")
    if mod and hasattr(mod, "budget_for_context_window"):
        try:
            result = mod.budget_for_context_window(context_window)
            return str(result), False
        except Exception as e:
            return f"error: {e}", True
    return "budget_config not available", True


def real_code_execution(code: str, language: str = "python") -> Tuple[str, bool]:
    """Run code via Hermes PTC or subprocess fallback."""
    if _ensure_loaded():
        result, err = real_execute_code(code)
        if not err:
            return result, False
    import tempfile
    suffix = ".py" if language == "python" else ".sh"
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(code)
        f_path = f.name
    try:
        if language == "python":
            cmd = [sys.executable, f_path]
        else:
            cmd = [language, f_path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else ""), r.returncode != 0
    finally:
        try:
            os.unlink(f_path)
        except OSError:
            pass


def real_patch_parser(patch_text: str) -> Tuple[str, bool]:
    """Parse v4a patch."""
    mod = _get("patch_parser")
    if mod and hasattr(mod, "parse_v4a_patch"):
        try:
            ops, error = mod.parse_v4a_patch(patch_text)
            return str(ops), error is not None
        except Exception as e:
            return f"error: {e}", True
    return "patch_parser not available", True


def real_discord_post(channel_id: str, message: str) -> Tuple[str, bool]:
    """Post to Discord."""
    mod = _get("discord_tool")
    if mod:
        for fn_name in ("send_message", "post_message", "send"):
            if hasattr(mod, fn_name):
                try:
                    return getattr(mod, fn_name)(channel_id, message), False
                except Exception as e:
                    return f"discord.{fn_name} failed: {e}", True
    return "discord_tool not available (DISCORD_BOT_TOKEN required)", True


# ===================== Status =====================

def get_bridge_status() -> Dict[str, Any]:
    """Report upstream integration status."""
    loaded = _ensure_loaded()
    tool_defs = get_openai_tool_definitions() if loaded else []
    return {
        "hermes_path": str(HERMES_PY),
        "model_tools_loaded": loaded,
        "tools_discovered": len(tool_defs),
    "total": len(tool_defs),
        "tool_names": [d.get("function", {}).get("name", "?") for d in tool_defs[:30]],
    }


if __name__ == "__main__":
    print(json.dumps(get_bridge_status(), indent=2))



# ===================== Backward-compat aliases (v1.8.2 API) =====================

# These aliases let old function_caller.py code keep working
real_terminal = real_terminal_run
real_code_execution_legacy = real_code_execution
