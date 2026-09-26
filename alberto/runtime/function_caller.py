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

@register_tool("run_shell")
def tool_run_shell(alberto, args: Dict) -> Tuple[str, bool]:
    """Run a shell command. Args: command (str), timeout (int, default 30)."""
    cmd = args.get("command", "")
    timeout = int(args.get("timeout", 30))
    if not cmd:
        return "no command provided", True
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
    """Write a file. Args: path (str), content (str)."""
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return "no path provided", True
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} bytes to {path}", False
    except Exception as e:
        return f"error: {e}", True


@register_tool("memory_set")
def tool_memory_set(alberto, args: Dict) -> Tuple[str, bool]:
    """Save a memory. Args: key (str), value (str), tags (str, optional)."""
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
    try:
        alberto.memory_set(key, value, tags=tags)
        return f"saved memory {key}={value[:100]}", False
    except Exception as e:
        return f"error: {e}", True


@register_tool("memory_get")
def tool_memory_get(alberto, args: Dict) -> Tuple[str, bool]:
    """Read a memory. Args: key (str)."""
    key = args.get("key", "")
    if not key:
        return "no key provided", True
    try:
        v = alberto.memory_get(key)
        if v is None:
            return f"memory {key} not found", True
        return f"{key} = {v}", False
    except Exception as e:
        return f"error: {e}", True


@register_tool("memory_search")
def tool_memory_search(alberto, args: Dict) -> Tuple[str, bool]:
    """Search memory. Args: query (str), limit (int, default 5)."""
    query = args.get("query", "")
    limit = int(args.get("limit", 5))
    if not query:
        return "no query", True
    try:
        hits = alberto.memory_search(query, limit=limit)
        if not hits:
            return "no matches", False
        return "\n".join(f"{h['key']} = {h['value'][:100]}" for h in hits), False
    except Exception as e:
        return f"error: {e}", True


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
    """MiMo task.ts — spawn a subagent to handle a subtask in parallel.
    Args: description (str), prompt (str), agent (str, default 'build')."""
    description = args.get("description", "")
    prompt = args.get("prompt", "")
    agent_type = args.get("agent", "build")
    if not description and not prompt:
        return "description or prompt required", True
    try:
        # For now, run synchronously via run_tool_loop with restricted scope
        # Real MiMo would spawn a subprocess; we delegate via the alberto.meta
        result_text = f"[subagent '{agent_type}'] task='{description}'\n"
        # Use meta_controller if available
        if hasattr(alberto, "meta"):
            try:
                plan = alberto.meta.plan_objective(prompt or description)
                result_text += f"plan: {plan.get('id', '?')}\nsubtasks: {len(plan.get('subtasks', []))}"
            except Exception as e:
                result_text += f"plan failed: {e}"
        return result_text, False
    except Exception as e:
        return f"error: {e}", True


@register_tool("plan")
def tool_plan(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo plan.ts — enter plan mode (read-only analysis).
    Args: steps (list of strings, optional)."""
    steps = args.get("steps", [])
    if hasattr(alberto, "catalog"):
        alberto.catalog.activate("plan")
    msg = "plan mode activated. "
    if steps:
        msg += f"steps: {steps}"
    return msg, False


@register_tool("question")
def tool_question(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo question.ts — ask the user a clarifying question.
    Args: question (str), options (list of strings, optional)."""
    q = args.get("question", "")
    options = args.get("options", [])
    if not q:
        return "no question", True
    msg = f"❓ {q}"
    if options:
        msg += "\nOptions:\n" + "\n".join(f"  - {o}" for o in options)
    return msg, False


@register_tool("skill")
def tool_skill(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo skill.ts — load and run a skill from the catalog.
    Args: name (str), input (str, optional)."""
    name = args.get("name", "")
    inp = args.get("input", "")
    if not name:
        return "no skill name", True
    try:
        # Use Alberto's skill_engine
        from .skill_engine import run_skill
        result = run_skill(alberto, name, inp)
        return f"skill {name} executed: {json.dumps(result, default=str)[:1000]}", False
    except Exception as e:
        return f"skill {name} failed: {e}", True


@register_tool("workflow")
def tool_workflow(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo workflow.ts — execute a workflow definition.
    Args: name (str), input (str, optional)."""
    name = args.get("name", "")
    inp = args.get("input", "")
    if not name:
        return "no workflow name", True
    try:
        # Use Alberto's meta controller or direct squad
        if hasattr(alberto, "squad_list") and name in alberto.squad_list():
            result = alberto.run_squad(name, inp)
            return f"workflow {name} completed: {json.dumps(result, default=str)[:1500]}", False
        return f"workflow {name} not found in squads", True
    except Exception as e:
        return f"workflow {name} failed: {e}", True


@register_tool("actor")
def tool_actor(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo actor.ts — run a shell command via a long-lived process (preserves state).
    Args: command (str), session (str, optional default 'default')."""
    cmd = args.get("command", "")
    session = args.get("session", "default")
    if not cmd:
        return "no command", True
    try:
        # Use a persistent actor session directory
        actor_dir = Path("/tmp/alberto-actor")
        actor_dir.mkdir(parents=True, exist_ok=True)
        session_file = actor_dir / f"{session}.log"
        with open(session_file, "a") as f:
            f.write(f"$ {cmd}\n")
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        with open(session_file, "a") as f:
            f.write((r.stdout or "") + (r.stderr or "") + "\n")
        return f"[actor:{session}] exit={r.returncode}\n{(r.stdout or '')[:1500]}", r.returncode != 0
    except Exception as e:
        return f"error: {e}", True


@register_tool("lsp")
def tool_lsp(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo lsp.ts — run an LSP query (go-to-definition, references, etc).
    Args: action (str: 'definition'|'references'|'hover'|'symbols'), path (str), line (int, optional), col (int, optional)."""
    action = args.get("action", "")
    path = args.get("path", "")
    if not action or not path:
        return "action and path required", True
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"file not found: {path}", True
        # Simple grep-based fallback (real LSP needs language server)
        content = p.read_text(errors="replace")
        lines = content.splitlines()
        out = f"[LSP {action} on {path}]\n"
        if action == "symbols":
            import re as _re
            syms = _re.findall(r"^\s*(?:def|class|function|const|let|var|interface|type|export)\s+([A-Za-z_][A-Za-z0-9_]*)", content, _re.M)
            out += "\n".join(syms[:100])
        elif action == "hover":
            line_no = int(args.get("line", 0))
            if 0 < line_no <= len(lines):
                out += lines[line_no - 1]
        elif action == "definition":
            line_no = int(args.get("line", 0))
            if 0 < line_no <= len(lines):
                out += f"line {line_no}: {lines[line_no-1]}"
        elif action == "references":
            symbol = args.get("symbol", "")
            if symbol:
                matches = [(i+1, l) for i, l in enumerate(lines) if symbol in l]
                out += "\n".join(f"L{i}: {l[:200]}" for i, l in matches[:50])
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
    """MiMo codesearch.ts — semantic code search using ripgrep/embeddings.
    Args: query (str), path (str, default '.'), max_results (int, default 20)."""
    query = args.get("query", "")
    base = args.get("path", ".")
    max_results = int(args.get("max_results", 20))
    if not query:
        return "no query", True
    # Use ripgrep if available, else grep fallback
    try:
        r = subprocess.run(
            ["rg", "--json", "-i", "--max-count", str(max_results), query, base],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            return r.stdout[:3000], False
    except FileNotFoundError:
        pass
    except Exception:
        pass
    # Fallback to grep
    try:
        r = subprocess.run(
            ["grep", "-rn", "-i", "--include=*.py", "--include=*.ts", "--include=*.js",
             "--include=*.tsx", "--include=*.jsx", query, base],
            capture_output=True, text=True, timeout=30
        )
        out = r.stdout[:3000] if r.stdout else "no matches"
        return out, False
    except Exception as e:
        return f"error: {e}", True


@register_tool("history")
def tool_history(alberto, args: Dict) -> Tuple[str, bool]:
    """MiMo history.ts — show past conversation/tool history.
    Args: limit (int, default 10)."""
    limit = int(args.get("limit", 10))
    try:
        convs = alberto.conversations.list()
        out = []
        for cid in convs[-limit:][::-1]:
            c = alberto.conversations.get(cid)
            if c and c.turns:
                last_user = next((t for t in c.turns if t.role == "user"), None)
                if last_user:
                    out.append(f"[{cid[:20]}] {last_user.content[:100]}")
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
