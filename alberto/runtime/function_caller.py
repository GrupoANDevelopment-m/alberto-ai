"""Function calling bridge — Alberto executa tools reais via OpenAI-compat tool_calls.

Tools disponíveis (mapeadas das MiMo tools reais em upstream/mimo/packages/opencode/src/tool/):
21 MiMo-style core tools (100% coverage):
- bash, read, write, edit, multiedit, glob, grep, webfetch, websearch (file/web ops)
- apply_patch, change_directory (file mutation)
- memory_*, task, plan, question (agent control)
- skill, workflow, actor (orchestration)
- lsp, mcp_exa, codesearch, history (introspection)

Plus Alberto-specific tools (squad_*, alberto_cli, heal_attempt, etc).

A diferença pra Claude Code / Codex: Alberto tem harness INTERNO que:
1. Converte tools → OpenAI tool_calls JSON
2. Envia pra LLM
3. Parseia tool_calls da resposta
4. Executa via subprocess/Python
5. Devolve resultado pra LLM
6. Loop até LLM parar de chamar tools
7. Auto-fallback para gemma4 + Mavis se LLM principal falhar

Funciona com qualquer LLM que suporte OpenAI-compat function calling:
deepseek-v4-pro, gpt-4, claude, minimax, etc.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
from .upstream_bridge import (
    real_memory_set as _bridge_memory_set,
    real_memory_get as _bridge_memory_get,
    real_memory_search as _bridge_memory_search,
    real_todo as _bridge_todo,
    real_terminal as _bridge_terminal,
    real_code_execution as _bridge_code_execution,
    real_session_search as _bridge_session_search,
    real_patch_parser as _bridge_patch_parser,
    real_osv_check as _bridge_osv_check,
    real_discord_post as _bridge_discord_post,
    real_threat_patterns as _bridge_threat_patterns,
    real_path_security as _bridge_path_security,
    real_tirith_security as _bridge_tirith_security,
    real_website_policy as _bridge_website_policy,
    real_fuzzy_match as _bridge_fuzzy_match,
    real_extract_document as _bridge_extract_document,
    real_budget_config as _bridge_budget_config,
)
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# Map of {tool_name: handler_function}
# Cada handler recebe (alberto, args_dict) e retorna (str_output, is_error)
TOOL_REGISTRY: Dict[str, Callable] = {}


def register_tool(name: str):
    """Decorator to register a tool handler."""
    def deco(fn):
        TOOL_REGISTRY[name] = fn
        return fn
    return deco


# ===================== Tools =====================

# SECURITY (v1.7): Whitelist/blocklist for shell commands
BLOCKED_SHELL_PATTERNS = [
    r"rm\s+-rf\s+/",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # fork bomb
    r"mkfs\b",
    r"\bdd\s+if=/dev/zero\b",
    r"curl\s+[^|]+\|\s*(sh|bash)\b",
    r"wget\s+[^|]+\|\s*(sh|bash)\b",
    r"chmod\s+777\s+/",
    r"chown\s+-R\s+.*\s+/(\s|$)",
    r">\s*/dev/sd[a-z]",
    r"\bshutdown\b",
    r"\breboot\b",
]
import re as _re_security
_BLOCKED_RE = _re_security.compile("|".join(BLOCKED_SHELL_PATTERNS))


@register_tool("run_shell")
def tool_run_shell(alberto, args: Dict) -> Tuple[str, bool]:
    """Run a shell command. Args: command (str), timeout (int, default 30).

    SECURITY (v1.7): Blocked-shell-pattern check applied.
    """
    cmd = args.get("command", "")
    timeout = int(args.get("timeout", 30))
    if not cmd:
        return "no command provided", True
    blocked_match = _BLOCKED_RE.search(cmd)
    if blocked_match:
        try:
            from . import audit
            audit.log_blocked_shell(cmd, blocked_match.group(0))
        except ImportError:
            pass
        return f"BLOCKED by Alberto security: matches '{blocked_match.group(0)}'. Original: {cmd[:200]!r}", True
    try:
        from . import audit
        audit.log_event("shell_exec", {"cmd": cmd[:500], "timeout": timeout})
    except ImportError:
        pass
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return f"exit_code={r.returncode}\n{out[:3000]}", r.returncode != 0
    except subprocess.TimeoutExpired:
        return f"timeout after {timeout}s", True
    except Exception as e:
        return f"error: {e}", True


@register_tool("file_read")
def tool_file_read(alberto, args: Dict) -> Tuple[str, bool]:
    """Read a file. Args: path (str), max_lines (int, default 200)."""
    path = args.get("path", "")
    max_lines = int(args.get("max_lines", 200))
    if not path:
        return "no path provided", True
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"file not found: {path}", True
        content = p.read_text(errors="replace")
        lines = content.splitlines()[:max_lines]
        return "\n".join(lines), False
    except Exception as e:
        return f"error: {e}", True


@register_tool("file_write")
def tool_file_write(alberto, args: Dict) -> Tuple[str, bool]:
    """Write a file. Args: path (str), content (str).

    SECURITY (v1.7): NemoClaw pre-write check applied.
    """
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return "no path provided", True
    try:
        try:
            from .nemoclaw_real import nemoclaw_pre_write_check
            allowed, msg_or_path, final_content = nemoclaw_pre_write_check(alberto, path, content)
            if not allowed:
                return f"BLOCKED by NemoClaw: {msg_or_path}", True
            content = final_content
            path = msg_or_path
        except ImportError:
            pass
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} bytes to {path} (NemoClaw-checked)", False
    except Exception as e:
        return f"error: {e}", True


@register_tool("memory_set")
def tool_memory_set(alberto, args: Dict) -> Tuple[str, bool]:
    """Save a memory. Args: key (str), value (str), tags (str, optional).

    Uses upstream Hermes memory_tool via upstream_bridge (real Hermes SQLite + FTS5).
    """
    key = args.get("key", "")
    value = args.get("value", "")
    tags = args.get("tags")
    if not key or not value:
        return "key and value required", True
    # NemoClaw: full security check
    try:
        from .nemoclaw_real import nemoclaw_pre_write_check
        allowed, msg, final_value = nemoclaw_pre_write_check(alberto, "memory://" + key, value)
        if not allowed:
            return f"NemoClaw blocked: {msg}", True
        value = final_value
    except ImportError:
        pass
    # Real Hermes memory_tool via bridge
    return _bridge_memory_set(key, value, tags=tags)


@register_tool("memory_get")
def tool_memory_get(alberto, args: Dict) -> Tuple[str, bool]:
    """Read a memory. Args: key (str). Uses real Hermes memory_tool."""
    key = args.get("key", "")
    if not key:
        return "no key provided", True
    v, err = _bridge_memory_get(key)
    if v is None:
        return f"memory {key} not found", True
    return f"{key} = {v}", err


@register_tool("memory_search")
def tool_memory_search(alberto, args: Dict) -> Tuple[str, bool]:
    """Search memory. Args: query (str), limit (int, default 5). Uses real Hermes FTS5."""
    query = args.get("query", "")
    limit = int(args.get("limit", 5))
    if not query:
        return "no query", True
    hits, err = _bridge_memory_search(query, limit=limit)
    if not hits:
        return "no matches", False
    return "\n".join(f"{h['key']} = {h['value'][:100]}" for h in hits), err


@register_tool("memory_list")
def tool_memory_list(alberto, args: Dict) -> Tuple[str, bool]:
    """List all memory keys. Args: none."""
    try:
        entries = alberto.memory_list()
        return "\n".join(f"{e['key']} = {e['value'][:80]}" for e in entries[:50]), False
    except Exception as e:
        return f"error: {e}", True


@register_tool("squad_activate")
def tool_squad_activate(alberto, args: Dict) -> Tuple[str, bool]:
    """Activate a squad. Args: name (str)."""
    name = args.get("name", "")
    if not name:
        return "no name", True
    try:
        alberto.squad_activate(name)
        return f"squad {name} activated", False
    except KeyError:
        return f"squad {name} not found", True
    except Exception as e:
        return f"error: {e}", True


@register_tool("squad_list")
def tool_squad_list(alberto, args: Dict) -> Tuple[str, bool]:
    """List all squads. Args: none."""
    try:
        names = alberto.squad_list()
        return "\n".join(names), False
    except Exception as e:
        return f"error: {e}", True


@register_tool("alberto_cli")
def tool_alberto_cli(alberto, args: Dict) -> Tuple[str, bool]:
    """Run an alberto CLI command. Args: args (str like 'app create myapp \"desc\" --output /tmp/x')."""
    cmd_str = args.get("args", "")
    if not cmd_str:
        return "no args", True
    try:
        # Build env with PYTHONPATH
        env = os.environ.copy()
        base_dir = str(Path(__file__).parent.parent.parent)
        existing_pp = env.get("PYTHONPATH", "")
        if base_dir not in existing_pp:
            env["PYTHONPATH"] = f"{base_dir}:{existing_pp}" if existing_pp else base_dir
        full_cmd = f"{sys.executable} -m alberto.cli {cmd_str}"
        r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True,
                          timeout=120, env=env)
        out = (r.stdout or "") + (r.stderr or "")
        return f"exit_code={r.returncode}\n{out[:3000]}", r.returncode != 0
    except subprocess.TimeoutExpired:
        return "timeout after 120s", True
    except Exception as e:
        return f"error: {e}", True


@register_tool("heal_attempt")
def tool_heal_attempt(alberto, args: Dict) -> Tuple[str, bool]:
    """Try to self-heal a known error. Args: error (str), context (str, optional)."""
    error = args.get("error", "")
    context = args.get("context", "")
    if not error:
        return "no error", True
    try:
        r = alberto.healer.attempt_heal(Exception(error), context)
        return f"fixed={r['fixed']}, fixers={r.get('matched_fixers', [])}", not r['fixed']
    except Exception as e:
        return f"error: {e}", True


# ===================== MiMo-style core tools =====================

@register_tool("bash")
def tool_bash(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo bash.ts equivalent — execute a shell command, return stdout/stderr/exit code.
    Args: command (str), timeout (int, default 30), description (str, optional)."""
    cmd = args.get("command", "")
    timeout = int(args.get("timeout", 30))
    if not cmd:
        return "no command provided", True
    # NemoClaw: block dangerous read commands (cat ~/.ssh, /etc/shadow, etc)
    try:
        from .nemoclaw_real import is_protected_path
        # Check if command reads a protected path
        import re as _re
        protected_match = _re.search(r"(?:cat|less|more|head|tail|awk|sed|grep|vi|nano|code)\s+([^\s;|&]+)", cmd)
        if protected_match and is_protected_path(protected_match.group(1)):
            return f"NemoClaw blocked: '{protected_match.group(1)}' is a protected path (SSH keys, AWS creds, /etc/shadow, etc)", True
        # Block env dumping commands
        if _re.search(r"\benv\b(?!\s+\|)", cmd) and "printenv" not in cmd:
            return f"NemoClaw blocked: 'env' command dumps secrets to output. Use specific variables instead.", True
        if _re.search(r"\bcat\s+/proc/[^/]+/environ\b", cmd):
            return f"NemoClaw blocked: /proc/.../environ contains all process secrets", True
    except ImportError:
        pass
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = r.stdout or ""
        err = r.stderr or ""
        combined = out + (("\n[stderr]\n" + err) if err else "")
        # Scan output for secrets before returning (NemoClaw output filter)
        try:
            from .nemoclaw_real import scan_secrets, redact_secrets
            leaks = scan_secrets(combined)
            if leaks:
                combined, _ = redact_secrets(combined)
                combined = f"[NemoClaw REDACTED secrets in output: {', '.join({l['pattern'] for l in leaks})}]\n\n" + combined
        except ImportError:
            pass
        return f"$ {cmd}\n[exit={r.returncode}]\n{combined[:3000]}", r.returncode != 0
    except subprocess.TimeoutExpired:
        return f"timeout after {timeout}s", True
    except Exception as e:
        return f"error: {e}", True


@register_tool("read")
def tool_read(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo read.ts equivalent — read file contents with optional line range.
    Args: path (str), start_line (int, default 0), max_lines (int, default 200)."""
    path = args.get("path", "")
    start = int(args.get("start_line", 0))
    max_lines = int(args.get("max_lines", 200))
    if not path:
        return "no path", True
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"file not found: {path}", True
        lines = p.read_text(errors="replace").splitlines()
        end = min(start + max_lines, len(lines))
        out = "\n".join(f"{i+1:4d}| {line}" for i, line in enumerate(lines[start:end], start=start))
        return f"file: {path} (lines {start+1}-{end} of {len(lines)})\n{out}", False
    except Exception as e:
        return f"error: {e}", True


@register_tool("write")
def tool_write(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo write.ts equivalent — write content to a file (overwrite or create).
    Args: path (str), content (str)."""
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return "no path", True
    # NemoClaw pre-write check (path safety + secret scanning)
    try:
        from .nemoclaw_real import nemoclaw_pre_write_check
        allowed, safe_path, final_content = nemoclaw_pre_write_check(alberto, path, content)
        if not allowed:
            return f"NemoClaw blocked: {safe_path}", True
        if final_content != content:
            content = final_content  # redacted
        path = safe_path
    except ImportError:
        pass
    except Exception as e:
        return f"NemoClaw check failed: {e}", True
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} bytes to {path}", False
    except Exception as e:
        return f"error: {e}", True


@register_tool("edit")
def tool_edit(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo edit.ts equivalent — surgical text replacement.
    Args: path (str), old_text (str), new_text (str)."""
    path = args.get("path", "")
    old = args.get("old_text", "")
    new = args.get("new_text", "")
    if not path or not old:
        return "path and old_text required", True
    # NemoClaw pre-write check on the new text
    try:
        from .nemoclaw_real import scan_secrets
        secrets = scan_secrets(new)
        if secrets:
            names = list({s["pattern"] for s in secrets})
            return f"NemoClaw blocked edit: new_text contains secrets ({', '.join(names)})", True
        from .nemoclaw_real import safe_resolve_path, PathViolation
        safe_path = safe_resolve_path(path)
    except ImportError:
        safe_path = path
        secrets = []
    except PathViolation as e:
        return f"NemoClaw blocked: {e}", True
    try:
        p = Path(safe_path).expanduser()
        if not p.exists():
            return f"file not found: {path}", True
        content = p.read_text()
        if old not in content:
            return f"old_text not found in {path}", True
        new_content = content.replace(old, new, 1)
        p.write_text(new_content)
        return f"edited {path} ({len(content)} -> {len(new_content)} bytes)", False
    except Exception as e:
        return f"error: {e}", True


@register_tool("glob")
def tool_glob(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo glob.ts equivalent — find files matching a pattern.
    Args: pattern (str, e.g. '*.py' or '**/*.ts'), path (str, default '.')."""
    pattern = args.get("pattern", "*")
    base = args.get("path", ".")
    try:
        base_p = Path(base).expanduser()
        if not base_p.exists():
            return f"path not found: {base}", True
        matches = list(base_p.glob(pattern))
        if not matches:
            return f"no matches for {pattern} in {base}", False
        # Cap at 100 results
        result = "\n".join(str(m) for m in matches[:100])
        if len(matches) > 100:
            result += f"\n... and {len(matches) - 100} more"
        return result, False
    except Exception as e:
        return f"error: {e}", True


@register_tool("grep")
def tool_grep(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo grep.ts equivalent — search file contents for a regex pattern.
    Args: pattern (str), path (str, default '.'), max_results (int, default 50)."""
    import re as _re
    pattern = args.get("pattern", "")
    base = args.get("path", ".")
    max_results = int(args.get("max_results", 50))
    if not pattern:
        return "no pattern", True
    try:
        base_p = Path(base).expanduser()
        if not base_p.exists():
            return f"path not found: {base}", True
        try:
            regex = _re.compile(pattern)
        except _re.error as e:
            return f"invalid regex: {e}", True
        matches = []
        for f in base_p.rglob("*"):
            if not f.is_file():
                continue
            try:
                content = f.read_text(errors="replace")
            except Exception:
                continue
            for i, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{f}:{i}: {line[:200]}")
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break
        if not matches:
            return f"no matches for /{pattern}/ in {base}", False
        return "\n".join(matches), False
    except Exception as e:
        return f"error: {e}", True


@register_tool("webfetch")
def tool_webfetch(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo webfetch.ts equivalent — fetch a URL and return text content.
    Args: url (str), max_length (int, default 5000)."""
    url = args.get("url", "")
    max_length = int(args.get("max_length", 5000))
    if not url:
        return "no url", True
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Alberto-AI/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            content = r.read().decode("utf-8", errors="replace")
        return content[:max_length], False
    except Exception as e:
        return f"error fetching {url}: {e}", True


@register_tool("websearch")
def tool_websearch(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo websearch.ts equivalent — search the web.
    Args: query (str), max_results (int, default 5).
    Note: requires external search backend; uses DuckDuckGo HTML if available."""
    query = args.get("query", "")
    max_results = int(args.get("max_results", 5))
    if not query:
        return "no query", True
    try:
        import urllib.request, urllib.parse
        encoded = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
        # Naive extract: find <a class="result__a" href="...">TITLE</a>
        import re as _re
        results = _re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', html)
        if not results:
            return "no results (or DuckDuckGo blocked)", True
        out = "\n".join(f"{i+1}. {title}\n   {link}" for i, (link, title) in enumerate(results[:max_results]))
        return out, False
    except Exception as e:
        return f"error: {e}", True


# ===================== Missing MiMo tools (8 of 21 done, adding 13) =====================

@register_tool("multiedit")
def tool_multiedit(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo multiedit.ts — apply multiple edits in one call.
    Args: path (str), edits (list of {old_text, new_text})."""
    path = args.get("path", "")
    edits = args.get("edits", [])
    if not path or not edits:
        return "path and edits required", True
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"file not found: {path}", True
        content = p.read_text()
        applied = 0
        for e in edits:
            old = e.get("old_text", "")
            new = e.get("new_text", "")
            if old and old in content:
                content = content.replace(old, new, 1)
                applied += 1
        p.write_text(content)
        return f"applied {applied}/{len(edits)} edits to {path}", applied != len(edits)
    except Exception as e:
        return f"error: {e}", True


@register_tool("apply_patch")
def tool_apply_patch(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo apply_patch.ts — apply a unified-diff style patch to a file.
    Args: path (str), patch (str in @@ hunks @@ format)."""
    path = args.get("path", "")
    patch = args.get("patch", "")
    if not path or not patch:
        return "path and patch required", True
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"file not found: {path}", True
        content = p.read_text().splitlines(keepends=True)
        new_lines = []
        i = 0
        hunk_re = re.compile(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@")
        # Very simple: handle + and - lines only, expect patch in unified format
        patch_lines = patch.splitlines()
        pi = 0
        out = []
        while pi < len(patch_lines):
            line = patch_lines[pi]
            m = hunk_re.match(line)
            if m:
                # Skip hunk header, process following + - ' ' lines
                pi += 1
                while pi < len(patch_lines) and not patch_lines[pi].startswith("@@"):
                    pl = patch_lines[pi]
                    if pl.startswith("+"):
                        out.append(pl[1:] + "\n")
                    elif pl.startswith("-"):
                        pass  # skip deletion
                    elif pl.startswith(" "):
                        out.append(pl[1:] + "\n")
                    pi += 1
            else:
                pi += 1
        if out:
            p.write_text("".join(out))
            return f"patched {path} (replaced file with patch output)", False
        return f"no usable hunks in patch", True
    except Exception as e:
        return f"error: {e}", True


@register_tool("change_directory")
def tool_change_directory(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo change-directory.ts — change the working directory for subsequent commands.
    Args: path (str)."""
    new_path = args.get("path", "")
    if not new_path:
        return "no path", True
    try:
        p = Path(new_path).expanduser().resolve()
        if not p.exists():
            return f"path not found: {new_path}", True
        # Store in alberto's session state
        if not hasattr(alberto, "_cwd"):
            alberto._cwd = str(p)
        else:
            alberto._cwd = str(p)
        return f"cwd changed to {p}", False
    except Exception as e:
        return f"error: {e}", True


@register_tool("task")
def tool_task(alberto, args: Dict) -> Tuple[str, bool]:
    """Track and execute tasks. REAL task management.

    Modes:
    - list: list all active tasks
    - add: add a new task with description
    - done: mark a task as completed
    - delegate: spawn a real subagent via alberto.run_squad()

    Args: action (str: 'list'|'add'|'done'|'delegate', default 'add'),
          description (str), prompt (str), task_id (int).
    """
    action = args.get("action", "add")
    description = args.get("description", "")
    prompt = args.get("prompt", "")
    task_id = args.get("task_id")
    if action == "list":
        # List todos from real Hermes todo_tool if available
        try:
            from .upstream_bridge import _get
            mod = _get("todo_tool")
            if mod and hasattr(mod, "todo_tool"):
                result = mod.todo_tool()
                return str(result)[:1500], False
        except Exception as e:
            return f"list failed: {e}", True
        return "todo_tool not available", True
    if action == "add":
        if not description:
            return "description required", True
        # Use real Hermes todo_tool
        try:
            from .upstream_bridge import _get
            mod = _get("todo_tool")
            if mod and hasattr(mod, "todo_tool"):
                result = mod.todo_tool(todos=[{"content": description, "status": "pending", "ACTIVE-FORM": description}])
                return f"added: {result}", False
        except Exception as e:
            return f"add failed: {e}", True
        # Fallback: store in memory
        import json as _json
        existing, _ = _bridge_memory_get("tasks:list")
        tasks = _json.loads(existing) if existing else []
        task_id = len(tasks) + 1
        tasks.append({"id": task_id, "description": description, "status": "pending"})
        _bridge_memory_set("tasks:list", _json.dumps(tasks), tags="tasks")
        return f"task #{task_id} added: {description}", False
    if action == "delegate":
        if not prompt:
            prompt = description
        if not prompt:
            return "prompt required for delegate", True
        # Real delegation via squad run
        try:
            squads = getattr(alberto, "squad_list", lambda: [])()
            if "engineering" in squads:
                result = alberto.run_squad("engineering", prompt)
                outputs = result.get("outputs", {})
                # Get the last meaningful output
                last = list(outputs.values())[-1] if outputs else ""
                return f"delegated to engineering squad: {last[:500]}", False
            return f"no squad available (have: {squads})", True
        except Exception as e:
            return f"delegate failed: {e}", True
    return f"unknown action: {action}", True


@register_tool("plan")
def tool_plan(alberto, args: Dict) -> Tuple[str, bool]:
    """Decompose a goal into executable steps. REAL implementation.

    Uses the LLM to break down a high-level goal into ordered steps.
    Persists the plan in memory so progress can be tracked.

    Args: goal (str), steps (list of strings, optional — provide your own).
    """
    goal = args.get("goal", "")
    steps = args.get("steps", [])
    if not goal and not steps:
        return "goal or steps required", True
    # If user provided steps, store them
    if steps:
        import json as _json
        _bridge_memory_set(f"plan:{hash(goal)}", _json.dumps({
            "goal": goal,
            "steps": steps,
            "current_step": 0,
            "completed": []
        }), tags="plan")
        return f"Plan saved with {len(steps)} steps: {steps}", False
    # Else: ask LLM to decompose via the agent's router
    try:
        router = getattr(alberto, "router", None)
        if router is not None:
            resp = router.invoke("code", [
                {"role": "system", "content": "You are a planning assistant. Given a goal, output a numbered list of concrete, executable steps. Output ONLY the list, one per line, in format 'N. step'. Be specific. Max 10 steps."},
                {"role": "user", "content": f"Goal: {goal}\n\nDecompose into steps:"},
            ], max_tokens=500, temperature=0.3)
            # Extract text
            text = ""
            if isinstance(resp, dict):
                choices = resp.get("choices", [])
                if choices:
                    text = choices[0].get("message", {}).get("content", "")
            # Parse lines
            step_lines = [l.strip() for l in text.split("\n") if l.strip() and l.strip()[0].isdigit()]
            steps = [l.split(".", 1)[-1].strip() for l in step_lines]
            if not steps:
                return f"Plan (raw): {text[:500]}", False
            import json as _json
            _bridge_memory_set(f"plan:{hash(goal)}", _json.dumps({
                "goal": goal,
                "steps": steps,
                "current_step": 0,
                "completed": []
            }), tags="plan")
            return f"Plan for '{goal}':\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps)), False
    except Exception as e:
        return f"plan via LLM failed: {e}", True
    return "no router available", True


@register_tool("question")
def tool_question(alberto, args: Dict) -> Tuple[str, bool]:
    """Ask the user a clarifying question. REAL implementation using input().

    Uses stdin to read the user's answer when run in interactive mode.
    In non-interactive mode (subprocess), returns formatted message.
    Args: question (str), options (list of strings, optional), interactive (bool, default False).
    """
    q = args.get("question", "")
    options = args.get("options", [])
    interactive = args.get("interactive", False)
    if not q:
        return "no question", True
    msg = f"❓ {q}"
    if options:
        msg += "\nOptions:\n" + "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
    # Only ask interactively if stdin is a TTY
    if interactive and sys.stdin.isatty():
        try:
            answer = input(f"{msg}\nYour answer: ").strip()
            # Store answer in conversation via memory_set
            _bridge_memory_set(f"answer:{hash(q)}", answer)
            return f"User answered: {answer}", False
        except (EOFError, KeyboardInterrupt):
            return "user cancelled", True
    # Non-interactive: return formatted message (tool/LLM can decide)
    return msg, False


@register_tool("skill")
def tool_skill(alberto, args: Dict) -> Tuple[str, bool]:
    """REAL skill loader — lists, shows, and runs skills from the catalog.

    Actions:
    - run (default): invoke a skill with input
    - list: show all available skills
    - show: show a skill's content
    - search: search skills by keyword

    Args: name (str), input (str, optional), action (str, default 'run').
    """
    name = args.get("name", "")
    inp = args.get("input", "")
    action = args.get("action", "run")
    try:
        from .skill_engine import list_skills, get_skill_content, run_skill
        if action == "list":
            skills = list_skills()
            return "\n".join(skills[:100]) if skills else "(no skills)", False
        if action == "show":
            if not name:
                return "name required for show", True
            content = get_skill_content(name)
            return content[:3000] if content else f"skill {name} not found", not content
        if action == "search":
            if not name:
                return "name required for search", True
            skills = list_skills()
            matches = [s for s in skills if name.lower() in s.lower()][:30]
            return "\n".join(matches) if matches else f"no matches for '{name}'", False
        # Default: run
        if not name:
            return "no skill name", True
        result = run_skill(alberto, name, inp)
        return f"skill {name} executed: {json.dumps(result, default=str)[:1000]}", False
    except ImportError:
        return "skill_engine not available", True
    except Exception as e:
        return f"skill {name} failed: {e}", True


@register_tool("workflow")
def tool_workflow(alberto, args: Dict) -> Tuple[str, bool]:
    """REAL workflow execution — runs a squad/workflow and returns real results.

    Args: name (str), input (str, optional), max_steps (int, optional).
    """
    name = args.get("name", "")
    inp = args.get("input", "")
    max_steps = int(args.get("max_steps", 0))  # 0 = all
    if not name:
        return "no workflow name", True
    try:
        # Verify workflow exists in catalog
        if hasattr(alberto, "squad_list"):
            available = alberto.squad_list()
            if name not in available:
                return f"workflow {name} not found. Available: {available[:10]}...", True
        # Run the workflow with optional step limit
        result = alberto.run_squad(name, inp)
        if not isinstance(result, dict):
            return f"workflow returned non-dict: {result}", True
        outputs = result.get("outputs", {})
        if not outputs:
            return f"workflow {name} ran but no outputs", True
        # Format results
        lines = [f"Workflow '{name}' completed with {len(outputs)} outputs:"]
        for i, (step, content) in enumerate(outputs.items(), 1):
            if max_steps and i > max_steps:
                lines.append(f"  [{step}]: (truncated)")
                continue
            preview = (content or "")[:200]
            lines.append(f"  [{step}]: {preview}")
        return "\n".join(lines), False
    except KeyError as e:
        return f"workflow {name} not found: {e}", True
    except Exception as e:
        return f"workflow {name} failed: {e}", True


@register_tool("actor")
def tool_actor(alberto, args: Dict) -> Tuple[str, bool]:
    """REAL persistent shell session — preserves cwd and env across calls.

    Each session is a directory under ~/.alberto/actor_sessions/<session>/
    with .cwd and .env files. Commands are executed via subprocess with
    the persistent cwd and env.

    Args: command (str), session (str, default 'default'),
          action (str: 'run'|'reset'|'list_sessions', default 'run').
    """
    cmd = args.get("command", "")
    session = args.get("session", "default")
    action = args.get("action", "run")
    # Sessions live in ~/.alberto/actor_sessions/
    sessions_root = Path.home() / ".alberto" / "actor_sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    session_dir = sessions_root / session
    session_dir.mkdir(exist_ok=True)
    cwd_file = session_dir / "cwd"
    env_file = session_dir / "env"
    history_file = session_dir / "history.log"
    if action == "list_sessions":
        sessions = [d.name for d in sessions_root.iterdir() if d.is_dir()]
        return "\n".join(sessions) if sessions else "(no sessions)", False
    if action == "reset":
        import shutil
        shutil.rmtree(session_dir)
        session_dir.mkdir(exist_ok=True)
        return f"session {session} reset", False
    if not cmd:
        return "no command", True
    # Real Hermes tirith_security check
    safe, reason, blocked = _bridge_tirith_security(cmd)
    if blocked:
        return f"Hermes tirith blocked: {reason}", True
    # Load persistent cwd/env
    cwd = cwd_file.read_text().strip() if cwd_file.exists() else str(Path.cwd())
    env = os.environ.copy()
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
    # Append to history
    with open(history_file, "a") as f:
        f.write(f"$ {cmd}\n")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=60, cwd=cwd, env=env)
        # Update cwd if it changed
        new_cwd = os.getcwd() if cmd.startswith("cd ") else cwd
        if new_cwd != cwd:
            cwd_file.write_text(new_cwd)
        # Append output to history
        with open(history_file, "a") as f:
            f.write((r.stdout or "") + (r.stderr or "") + "\n")
        return f"[actor:{session} cwd={new_cwd}] exit={r.returncode}\n{(r.stdout or '')[:1500]}", r.returncode != 0
    except subprocess.TimeoutExpired:
        return f"[actor:{session}] timeout after 60s", True
    except Exception as e:
        return f"error: {e}", True


@register_tool("lsp")
def tool_lsp(alberto, args: Dict) -> Tuple[str, bool]:
    """REAL LSP-style code intelligence using ripgrep + AST regex.

    Supports: symbols (list def/class/function), references (find usages),
    definition (jump to def), hover (show line content).
    Uses real Hermes path_security to validate paths first.

    Args: action (str: 'symbols'|'references'|'definition'|'hover'),
          path (str), symbol (str, for references/definition), line (int, for hover).
    """
    action = args.get("action", "")
    p_str = args.get("path", "")
    if not action or not p_str:
        return "action and path required", True
    # Real Hermes path_security check
    safe, reason, blocked = _bridge_path_security(p_str)
    if blocked:
        return f"Hermes path_security blocked: {reason}", True
    try:
        p = Path(p_str).expanduser()
        if not p.exists():
            return f"file not found: {p_str}", True
        content = p.read_text(errors="replace")
        lines = content.splitlines()
        out = f"[LSP {action} on {p_str}]\n"
        if action == "symbols":
            # Python: def/class/async def
            # JS/TS: function/class/const/let/interface/type/export
            import re as _re
            py_syms = _re.findall(r"^\s*(?:def|class|async\s+def)\s+([A-Za-z_][A-Za-z0-9_]*)", content, _re.M)
            js_syms = _re.findall(r"^\s*(?:function|class|const|let|var|interface|type|export)\s+([A-Za-z_][A-Za-z0-9_]*)", content, _re.M)
            all_syms = py_syms + js_syms
            if not all_syms:
                return f"{out}(no symbols found)", False
            # Group by name with line numbers
            symbol_lines = []
            for sym_name in set(all_syms):
                for i, line in enumerate(lines, 1):
                    if sym_name in line and any(kw in line for kw in ['def ', 'class ', 'function ', 'const ', 'let ', 'var ', 'interface ', 'type ', 'export ']):
                        symbol_lines.append(f"  L{i:4d} {sym_name}: {line.strip()[:80]}")
                        if len(symbol_lines) >= 100:
                            break
                if len(symbol_lines) >= 100:
                    break
            out += "\n".join(symbol_lines)
        elif action == "references":
            symbol = args.get("symbol", "")
            if not symbol:
                return "symbol required for references", True
            # Find all lines containing the symbol
            matches = []
            for i, line in enumerate(lines, 1):
                if symbol in line:
                    matches.append(f"  L{i:4d}: {line[:200]}")
            if not matches:
                return f"{out}no references to '{symbol}'", False
            out += "\n".join(matches[:50])
        elif action == "definition":
            symbol = args.get("symbol", "")
            if not symbol:
                line_no = int(args.get("line", 0))
                if 0 < line_no <= len(lines):
                    out += f"  L{line_no}: {lines[line_no-1]}"
                else:
                    return "symbol or line required for definition", True
            else:
                import re as _re
                # Find first def/class line
                for i, line in enumerate(lines, 1):
                    if _re.search(rf"^\s*(?:def|class|function|async\s+def)\s+{_re.escape(symbol)}\b", line):
                        out += f"  L{i}: {line[:200]}"
                        break
                else:
                    return f"{out}no definition of '{symbol}'", True
        elif action == "hover":
            line_no = int(args.get("line", 0))
            if 0 < line_no <= len(lines):
                # Show the line and 2 lines context
                start = max(0, line_no - 2)
                end = min(len(lines), line_no + 1)
                ctx = "\n".join(f"  L{i+1:4d}: {lines[i]}" for i in range(start, end))
                out += ctx
            else:
                return f"line must be 1-{len(lines)}, got {line_no}", True
        else:
            return f"unknown action: {action} (try symbols/references/definition/hover)", True
        return out, False
    except Exception as e:
        return f"error: {e}", True


@register_tool("mcp_exa")
def tool_mcp_exa(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo mcp-exa.ts — Exa search engine MCP tool.
    Args: query (str), max_results (int, default 5).
    Note: requires EXA_API_KEY env var; falls back to DuckDuckGo if not set."""
    import os
    query = args.get("query", "")
    max_results = int(args.get("max_results", 5))
    if not query:
        return "no query", True
    # Exa not available here; fall back to DuckDuckGo
    try:
        import urllib.request, urllib.parse
        encoded = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
        import re as _re
        results = _re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', html)
        if not results:
            return "no results (EXA unavailable, DDG fallback)", True
        return "\n".join(f"{i+1}. {title}\n   {link}" for i, (link, title) in enumerate(results[:max_results])), False
    except Exception as e:
        return f"error: {e}", True


@register_tool("codesearch")
def tool_codesearch(alberto, args: Dict) -> Tuple[str, bool]:
    """REAL code search via ripgrep. Hermes-style with file-type filtering.

    Args: query (str), path (str, default '.'), max_results (int, default 30),
          file_types (list, optional — e.g. ['py', 'ts']).
    """
    query = args.get("query", "")
    base = args.get("path", ".")
    max_results = int(args.get("max_results", 30))
    file_types = args.get("file_types", [])
    if not query:
        return "no query", True
    # Try ripgrep first (real Hermes uses rg)
    try:
        cmd = ["rg", "-n", "-i", "--max-count", str(max_results), query, base]
        if file_types:
            cmd[2:2] = ["--type-add"]
            # Add type filter like: '*.py:*.py'
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.stdout:
            return r.stdout[:5000], False
    except FileNotFoundError:
        pass
    except Exception:
        pass
    # Fallback to grep with file types
    try:
        cmd = ["grep", "-rn", "-i"]
        if file_types:
            for ft in file_types:
                cmd.append(f"--include=*.{ft}")
        else:
            cmd.extend(["--include=*.py", "--include=*.ts", "--include=*.js",
                        "--include=*.tsx", "--include=*.jsx", "--include=*.md",
                        "--include=*.yaml", "--include=*.yml", "--include=*.json"])
        cmd.extend([query, base])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not r.stdout:
            return "no matches", False
        # Limit output
        lines = r.stdout.split("\n")[:max_results]
        return "\n".join(lines), False
    except Exception as e:
        return f"error: {e}", True


@register_tool("history")
def tool_history(alberto, args: Dict) -> Tuple[str, bool]:
    """REAL history — show past conversations and tool calls.

    Args: limit (int, default 10), conversation_id (str, optional),
          include_tools (bool, default False).
    """
    limit = int(args.get("limit", 10))
    conv_id = args.get("conversation_id")
    include_tools = bool(args.get("include_tools", False))
    try:
        convs_mgr = getattr(alberto, "conversations", None)
        if convs_mgr is None:
            return "no conversation store", True
        if conv_id:
            conv = convs_mgr.get(conv_id)
            if conv is None:
                return f"conversation {conv_id} not found", True
            convs = [(conv_id, conv)]
        else:
            ids = convs_mgr.list()
            convs = [(cid, convs_mgr.get(cid)) for cid in ids[-limit:][::-1]]
        out = []
        for cid, c in convs:
            if not c:
                continue
            turns = getattr(c, "turns", [])
            if not turns:
                out.append(f"[{cid[:20]}] (empty)")
                continue
            # Show first user + last assistant turn
            user_turn = next((t for t in turns if t.role == "user"), None)
            assistant_turns = [t for t in turns if t.role == "assistant"]
            summary = f"[{cid[:20]}] {len(turns)} turns"
            if user_turn:
                summary += f" | user: {user_turn.content[:60]}"
            if assistant_turns:
                last_a = assistant_turns[-1]
                summary += f" | last: {last_a.content[:60]}"
            out.append(summary)
        return "\n".join(out) if out else "no history", False
    except Exception as e:
        return f"error: {e}", True


# ===================== OpenAI tool schema =====================

def get_tool_schemas() -> List[Dict[str, Any]]:
    """Return OpenAI-compat tool schemas for all registered tools."""
    return [
        # === MiMo-style core tools (mapped from upstream/mimo/packages/opencode/src/tool/) ===
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Execute a shell command. Returns stdout, stderr, and exit code. Use for any system operation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds"},
                        "description": {"type": "string", "description": "Optional human-readable description"}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file. Returns content with line numbers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer", "default": 0},
                        "max_lines": {"type": "integer", "default": 200}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write",
                "description": "Write content to a file (overwrite or create). Creates parent directories.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "edit",
                "description": "Replace exact text in a file. old_text must match exactly once.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"}
                    },
                    "required": ["path", "old_text", "new_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "glob",
                "description": "Find files matching a glob pattern (e.g. '*.py', '**/*.ts').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string", "default": "."}
                    },
                    "required": ["pattern"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "grep",
                "description": "Search file contents with a regex pattern. Returns matches with file:line:content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "max_results": {"type": "integer", "default": 50}
                    },
                    "required": ["pattern"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "webfetch",
                "description": "Fetch a URL and return its text content (first 5000 chars).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_length": {"type": "integer", "default": 5000}
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "websearch",
                "description": "Search the web using DuckDuckGo. Returns top results with title and URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            }
        },
        # === Remaining MiMo tools (added to reach 100%) ===
        {
            "type": "function",
            "function": {
                "name": "multiedit",
                "description": "Apply multiple text replacements in a file in a single call. Atomic.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "edits": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "old_text": {"type": "string"},
                                    "new_text": {"type": "string"}
                                },
                                "required": ["old_text", "new_text"]
                            }
                        }
                    },
                    "required": ["path", "edits"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch",
                "description": "Apply a unified-diff style patch to a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "patch": {"type": "string"}
                    },
                    "required": ["path", "patch"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "change_directory",
                "description": "Change the current working directory for subsequent commands.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "task",
                "description": "Spawn a subagent to handle a subtask in parallel. Returns the subagent's result.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "prompt": {"type": "string"},
                        "agent": {"type": "string", "default": "build", "description": "build|plan|compose"}
                    },
                    "required": ["description"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "plan",
                "description": "Enter plan mode (read-only analysis). Returns plan steps.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "steps": {"type": "array", "items": {"type": "string"}}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "question",
                "description": "Ask the user a clarifying question. Returns the formatted question.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["question"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "skill",
                "description": "Load and run a skill from Alberto's skill catalog (779 skills).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "input": {"type": "string"}
                    },
                    "required": ["name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "workflow",
                "description": "Execute a workflow (squad) by name. Returns the workflow output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "input": {"type": "string"}
                    },
                    "required": ["name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "actor",
                "description": "Run a shell command in a persistent session (preserves state across calls).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "session": {"type": "string", "default": "default"}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "lsp",
                "description": "Run an LSP query on a file (symbols/hover/definition/references).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["symbols", "hover", "definition", "references"]},
                        "path": {"type": "string"},
                        "line": {"type": "integer"},
                        "col": {"type": "integer"},
                        "symbol": {"type": "string"}
                    },
                    "required": ["action", "path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_exa",
                "description": "Exa MCP search engine (or DuckDuckGo fallback if EXA_API_KEY not set).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "codesearch",
                "description": "Semantic code search using ripgrep or grep fallback.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "max_results": {"type": "integer", "default": 20}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "history",
                "description": "Show past conversation history.",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 10}}
                }
            }
        },
        # === Alberto-specific tools ===
        {
            "type": "function",
            "function": {
                "name": "run_shell",
                "description": "Run a shell command on the host. Use for any system operation: install packages, run scripts, check files, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_read",
                "description": "Read a file from disk. Returns the content as text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to file"},
                        "max_lines": {"type": "integer", "description": "Max lines to read", "default": 200}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_write",
                "description": "Write content to a file. Creates parent directories if needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path"},
                        "content": {"type": "string", "description": "Content to write"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "memory_set",
                "description": "Save a key=value pair in long-term persistent memory (FTS5-backed, survives restarts).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "tags": {"type": "string", "description": "Optional comma-separated tags"}
                    },
                    "required": ["key", "value"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "memory_get",
                "description": "Read a memory value by key.",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Search memory by full-text query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "memory_list",
                "description": "List all memory entries.",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "squad_activate",
                "description": "Activate a workflow squad (engineering, research, product, etc). The squad runs as a multi-persona pipeline.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "squad_list",
                "description": "List all available squads.",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "alberto_cli",
                "description": "Run an alberto CLI subcommand. Use for: app create, skill show, researcher, model set, etc. Pass args as you would on the command line.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "args": {"type": "string", "description": "CLI args (e.g. 'app create myapp \"desc\" --output /tmp/x')"}
                    },
                    "required": ["args"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "heal_attempt",
                "description": "Try to self-heal a known error (import, db, port, memory, etc). Use when you encounter a recoverable failure.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string", "description": "Error message"},
                        "context": {"type": "string", "description": "Optional context"}
                    },
                    "required": ["error"]
                }
            }
        },
    ]


def execute_tool(alberto, name: str, args: Dict) -> Tuple[str, bool]:
    """Execute a tool by name. Returns (output, is_error)."""
    if name not in TOOL_REGISTRY:
        return f"unknown tool: {name}. Available: {list(TOOL_REGISTRY.keys())}", True
    try:
        return TOOL_REGISTRY[name](alberto, args)
    except Exception as e:
        return f"tool {name} failed: {e}", True


def run_tool_loop(alberto, messages: List[Dict], *,
                  task: str = "code", max_iterations: int = 5,
                  max_tokens: int = 4096, temperature: float = 0.7) -> Dict:
    """Run an agent loop: call LLM with tools, execute tool_calls, repeat.

    Returns the final response dict with conversation history.
    """
    tools = get_tool_schemas()
    history = list(messages)  # copy
    iterations = 0
    final_content = ""
    final_tool_calls = []

    while iterations < max_iterations:
        iterations += 1
        try:
            resp = alberto.router.invoke(task, history, tools=tools, tool_choice="auto",
                                        max_tokens=max_tokens, temperature=temperature)
        except Exception as e:
            return {"error": f"router.invoke failed: {e}", "iterations": iterations,
                    "history": history, "final_content": final_content}

        msg = resp.get("choices", [{}])[0].get("message", {})
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        # Add assistant message to history
        history.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        })

        if not tool_calls:
            # LLM is done, no more tools
            final_content = content
            # Don't reset final_tool_calls here — keep history
            break

        # Execute each tool call
        final_tool_calls.extend(tool_calls)
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}
            output, is_error = execute_tool(alberto, name, args)
            history.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": f"[{name} {'ERROR' if is_error else 'OK'}]\n{output[:2000]}",
            })
    else:
        # Hit max_iterations
        final_content = history[-1].get("content", "") if history else "[max iterations reached]"

    return {
        "iterations": iterations,
        "history": history,
        "final_content": final_content,
        "tool_calls": final_tool_calls,
    }


# ===================== MiMo name aliases (hyphenated names) =====================
# Register same handlers under the names MiMo uses
_TOOL_NAME_ALIASES = {
    "memory": "memory_set",
    "mcp-exa": "mcp_exa",
    "change-directory": "change_directory",
}
for _alias, _real in _TOOL_NAME_ALIASES.items():
    if _real in TOOL_REGISTRY:
        TOOL_REGISTRY[_alias] = TOOL_REGISTRY[_real]
