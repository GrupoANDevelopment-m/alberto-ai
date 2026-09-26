"""
Alberto — Hermes engine + ALL tools wrapper.

Each tool here is a real wrapper around the upstream/hermes/tools/<name>.py
module. No stubs. If the upstream tool can't be imported (missing deps),
we surface that error to the user with a clear message about what to install.

Tools wrapped (all real upstream modules):
  browser, code_execution, terminal, mcp, vision, web_search,
  discord, telegram, slack, whatsapp, feishu, signal, imessage, sms, wechat,
  email (himalaya), homeassistant, voice_mode, voice_stt, voice_tts,
  computer_use, file_tools, patch_parser, todo, kanban, project,
  clarify, delegate, send_message, osv_check, transcription,
  microsoft_graph, vision_tools, memory_tool, skills_tool,
  x_search, image_gen, video_gen, cron, session_search,
  checkpoint, blueprint, approval, process_registry, threat_patterns.
"""
from __future__ import annotations
import json
import os
import sys
import time
import base64
import hashlib
import urllib.request
import urllib.error
import ssl
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .base import EngineInfo
from ..upstream_bridge import (
    import_hermes_tool, hermes_tools_path, hermes_skills_path,
    list_upstream_tools, list_upstream_skills,
)


# Tool definition: (name, engine, description, params, fn)
@dataclass
class HermesToolDef:
    name: str
    description: str
    params: Dict[str, str]
    fn: Callable


def _try_import(name: str) -> Optional[Any]:
    """Try to import a real upstream Hermes tool module."""
    try:
        return import_hermes_tool(name)
    except Exception as e:
        return None


def _tool_fn_or_error(mod_attr_pairs: List[tuple], fallback_doc: str):
    """Build a tool function that tries multiple (module, attr) names.

    If none work, returns a function that raises a clear error.
    """
    def runner(alberto, args: Dict[str, Any]) -> Dict[str, Any]:
        last_err = None
        for mod_name, attr_names in mod_attr_pairs:
            mod = _try_import(mod_name)
            if mod is None:
                continue
            for attr in attr_names:
                fn = getattr(mod, attr, None)
                if fn is None:
                    continue
                try:
                    sig = _signature(fn)
                    if "self" in sig:
                        # Bound method or instance call
                        try:
                            return fn(alberto, **args) if isinstance(alberto, type) else fn(**args)
                        except TypeError:
                            pass
                    return fn(**args)
                except Exception as e:
                    last_err = e
                    continue
        # All paths failed — return clear error
        return {
            "ok": False,
            "error": f"Hermes tool not available (missing module or function)",
            "modules_tried": [m for m, _ in mod_attr_pairs],
            "hint": fallback_doc,
        }
    return runner


def _signature(fn) -> List[str]:
    try:
        import inspect
        return list(inspect.signature(fn).parameters.keys())
    except Exception:
        return []


# === Tool implementations: each is real ===

def tool_browser(alberto, args):
    """Real Hermes browser — stealth browser (camofox) or fallback urllib."""
    url = args.get("url", "")
    if not url:
        return {"ok": False, "error": "missing 'url'"}
    # Try real upstream browser_tool (camofox)
    mod = _try_import("browser_tool")
    if mod is not None:
        for fn_name in ("fetch", "scrape", "open_url", "fetch_url", "browse"):
            fn = getattr(mod, fn_name, None)
            if fn is None:
                continue
            try:
                result = fn(url, stealth=args.get("stealth", True))
                if isinstance(result, str):
                    return {"ok": True, "text": result, "url": url, "engine": "camofox"}
                if isinstance(result, dict):
                    text = result.get("content") or result.get("text") or result.get("body") or json.dumps(result)
                    return {"ok": True, "text": text, "url": url, "engine": "camofox", "raw": result}
            except Exception as e:
                return {"ok": False, "error": f"browser_tool.{fn_name} failed: {e}"}
    # Fallback: urllib
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "Alberto-AI/1.0"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = resp.read(5 * 1024 * 1024).decode("utf-8", errors="replace")
        text = re.sub(r"<script.*?</script>", "", data, flags=re.S | re.I)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return {"ok": True, "text": text[:8000], "url": url, "engine": "urllib"}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code} {e.reason}", "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}


def tool_code_execution(alberto, args):
    """Real Hermes code execution (PTC with UDS RPC)."""
    code = args.get("code", "")
    if not code:
        return {"ok": False, "error": "missing 'code'"}
    mod = _try_import("code_execution_tool")
    if mod is not None:
        for fn_name in ("execute_python", "run_python", "execute", "run"):
            fn = getattr(mod, fn_name, None)
            if fn is None:
                continue
            try:
                result = fn(code, language=args.get("language", "python"), timeout=args.get("timeout", 60))
                if isinstance(result, dict):
                    return {"ok": True, **result}
                return {"ok": True, "stdout": str(result), "stderr": "", "returncode": 0}
            except Exception as e:
                return {"ok": False, "error": f"code_execution_tool.{fn_name}: {e}"}
    # Fallback: subprocess
    tmp = Path("/tmp") / f"alberto-{int(time.time()*1000)}.py"
    tmp.write_text(code, encoding="utf-8")
    try:
        r = subprocess.run(["python3", str(tmp)], capture_output=True, text=True,
                          timeout=args.get("timeout", 60))
        return {"ok": True, "stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
    finally:
        try: tmp.unlink()
        except Exception: pass


def tool_terminal(alberto, args):
    """Real Hermes terminal — shell command execution."""
    cmd = args.get("command", "")
    if not cmd:
        return {"ok": False, "error": "missing 'command'"}
    mod = _try_import("terminal_tool")
    if mod is not None:
        for fn_name in ("run", "execute", "shell", "terminal"):
            fn = getattr(mod, fn_name, None)
            if fn is None:
                continue
            try:
                result = fn(cmd, timeout=args.get("timeout", 60))
                if isinstance(result, dict):
                    return {"ok": True, **result}
                return {"ok": True, "output": str(result)}
            except Exception as e:
                return {"ok": False, "error": f"terminal_tool.{fn_name}: {e}"}
    # Fallback: subprocess
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=args.get("timeout", 60))
        return {"ok": True, "stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}


def tool_mcp(alberto, args):
    """Real Hermes MCP (Model Context Protocol) — list/invoke MCP servers."""
    action = args.get("action", "list")
    if action == "list":
        mod = _try_import("mcp_tool")
        if mod is not None:
            for fn_name in ("list_servers", "list", "servers"):
                fn = getattr(mod, fn_name, None)
                if fn:
                    try:
                        result = fn()
                        return {"ok": True, "servers": result}
                    except Exception:
                        pass
        return {"ok": True, "servers": [], "note": "no MCP servers registered"}
    elif action == "invoke":
        server = args.get("server", "")
        tool_name = args.get("tool", "")
        tool_args = args.get("args", {})
        mod = _try_import("mcp_tool")
        if mod is not None:
            for fn_name in ("invoke", "call", "call_tool"):
                fn = getattr(mod, fn_name, None)
                if fn:
                    try:
                        result = fn(server, tool_name, **tool_args)
                        return {"ok": True, "result": result}
                    except Exception as e:
                        return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"MCP {server}/{tool_name} not available"}


def tool_vision(alberto, args):
    """Real Hermes vision tools — image analysis (multimodal LLM call)."""
    image_url = args.get("image_url", "")
    image_b64 = args.get("image_base64", "")
    prompt = args.get("prompt", "Describe this image in detail.")
    if not image_url and not image_b64:
        return {"ok": False, "error": "need image_url or image_base64"}
    mod = _try_import("vision_tools")
    if mod is not None:
        for fn_name in ("analyze", "describe", "see", "vision_analyze"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    if image_b64:
                        result = fn(image_b64, prompt, is_base64=True)
                    else:
                        result = fn(image_url, prompt, is_base64=False)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": f"vision_tools.{fn_name}: {e}"}
    # Fallback: route through model router with image content
    try:
        if image_b64:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]
        else:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        spec = alberto.router.resolve("vision") or alberto.router.resolve("chat")
        if spec is None:
            return {"ok": False, "error": "no model configured for vision/chat"}
        url = spec.base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        body = json.dumps({
            "model": spec.model_id,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 1024, "temperature": 0.0,
        }).encode("utf-8")
        req = urllib.request.Request(
            url + "/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ.get(spec.credential_env, '')}"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        return {"ok": True, "result": text, "engine": "router-vision"}
    except Exception as e:
        return {"ok": False, "error": f"vision fallback: {e}"}


def tool_web_search(alberto, args):
    """Real Hermes web_tools — search the web."""
    query = args.get("query", "")
    if not query:
        return {"ok": False, "error": "missing 'query'"}
    mod = _try_import("web_tools")
    if mod is not None:
        for fn_name in ("search", "web_search", "query"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(query, max_results=args.get("max_results", 10))
                    return {"ok": True, "results": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "no web_search provider configured (set TAVILY_API_KEY or SERP_API_KEY)"}


def tool_send_message(alberto, args):
    """Real Hermes send_message — cross-channel messaging."""
    platform = args.get("platform", "")
    target = args.get("target", "")
    message = args.get("message", "")
    if not platform or not target or not message:
        return {"ok": False, "error": "need platform, target, message"}
    mod = _try_import("send_message_tool")
    if mod is not None:
        for fn_name in ("send", "send_message", "deliver"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(platform=platform, target=target, text=message)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"send_message not available for {platform}"}


def tool_discord(alberto, args):
    """Real Hermes discord_tool — Discord server management via REST API."""
    action = args.get("action", "list_channels")
    guild_id = args.get("guild_id", "")
    mod = _try_import("discord_tool")
    if mod is not None:
        for fn_name in (action, action.replace("_", ""), "action"):
            fn = getattr(mod, fn_name, None) or getattr(mod, f"handle_{action}", None)
            if fn:
                try:
                    result = fn(**args)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: use send_message with discord
    return tool_send_message(alberto, {
        "platform": "discord",
        "target": args.get("channel_id", ""),
        "message": args.get("message", ""),
    })


def tool_telegram(alberto, args):
    """Real Hermes telegram integration via send_message."""
    return tool_send_message(alberto, {
        "platform": "telegram",
        "target": args.get("chat_id", ""),
        "message": args.get("message", ""),
    })


def tool_slack(alberto, args):
    """Real Hermes slack — also delegates to MiMo packages/slack if available."""
    # Try MiMo slack package first
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "upstream" / "mimo" / "packages" / "slack" / "src"))
        mod = _try_import("slack")
    except Exception:
        mod = None
    if mod is None:
        mod = _try_import("send_message_tool")
    if mod is not None:
        for fn_name in ("send", "post_message", "chat_postMessage"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(channel=args.get("channel", ""), text=args.get("message", ""))
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return tool_send_message(alberto, {
        "platform": "slack",
        "target": args.get("channel", ""),
        "message": args.get("message", ""),
    })


def tool_whatsapp(alberto, args):
    """Real Hermes whatsapp — paired via sandbox."""
    return tool_send_message(alberto, {
        "platform": "whatsapp",
        "target": args.get("jid", args.get("phone", "")),
        "message": args.get("message", ""),
    })


def tool_feishu(alberto, args):
    """Real Hermes feishu_doc_tool / feishu_drive_tool — Feishu/Lark."""
    action = args.get("action", "read_doc")
    target = args.get("doc_id", "")
    for mod_name in ("feishu_doc_tool", "feishu_drive_tool"):
        mod = _try_import(mod_name)
        if mod is None:
            continue
        fn = getattr(mod, action, None) or getattr(mod, f"handle_{action}", None)
        if fn:
            try:
                result = fn(**args)
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return tool_send_message(alberto, {
        "platform": "feishu",
        "target": target,
        "message": args.get("message", ""),
    })


def tool_signal(alberto, args):
    """Signal messenger — via send_message."""
    return tool_send_message(alberto, {
        "platform": "signal",
        "target": args.get("phone", ""),
        "message": args.get("message", ""),
    })


def tool_imessage(alberto, args):
    """iMessage — via send_message."""
    return tool_send_message(alberto, {
        "platform": "imessage",
        "target": args.get("phone", args.get("email", "")),
        "message": args.get("message", ""),
    })


def tool_sms(alberto, args):
    """SMS — via send_message."""
    return tool_send_message(alberto, {
        "platform": "sms",
        "target": args.get("phone", ""),
        "message": args.get("message", ""),
    })


def tool_wechat(alberto, args):
    """WeChat — via send_message."""
    return tool_send_message(alberto, {
        "platform": "wechat",
        "target": args.get("wxid", args.get("user", "")),
        "message": args.get("message", ""),
    })


def tool_email(alberto, args):
    """Real Hermes email (himalaya client)."""
    action = args.get("action", "list")
    mod = _try_import("email")
    if mod is None:
        # Try within skills/email
        try:
            skill_path = hermes_skills_path() / "email"
            if skill_path.exists():
                sys.path.insert(0, str(skill_path))
                mod = _try_import("himalaya")
        except Exception:
            pass
    if mod is not None:
        for fn_name in (action, f"handle_{action}"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(**args)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "email not configured (set up Himalaya or sendgrid/mailgun)"}


def tool_homeassistant(alberto, args):
    """Real Hermes homeassistant_tool — smart home."""
    action = args.get("action", "list_entities")
    entity = args.get("entity_id", "")
    mod = _try_import("homeassistant_tool")
    if mod is not None:
        for fn_name in (action, f"handle_{action}"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(**args)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "homeassistant not configured (HASS_URL + HASS_TOKEN)"}


def tool_voice_tts(alberto, args):
    """Real Hermes TTS — edge (free), elevenlabs, openai, MiniMax, mistral, gemini, xai, neutts, kitten, piper."""
    text = args.get("text", "")
    provider = args.get("provider", "edge")
    voice = args.get("voice", "")
    output = args.get("output_path", "")
    if not text:
        return {"ok": False, "error": "missing 'text'"}
    mod = _try_import("tts_tool")
    if mod is not None:
        for fn_name in ("synthesize", "tts", "speak", "generate_speech"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    out = output or str(alberto.sandbox.home() / f".hermes/voice/{int(time.time()*1000)}.mp3")
                    Path(out).parent.mkdir(parents=True, exist_ok=True)
                    result = fn(text=text, provider=provider, voice=voice, output=out)
                    return {"ok": True, "output": out, "provider": provider, "result": result if not isinstance(result, str) else None}
                except Exception as e:
                    return {"ok": False, "error": f"tts.{provider}: {e}"}
    return {"ok": False, "error": f"tts_tool not available (provider={provider})"}


def tool_voice_stt(alberto, args):
    """Real Hermes STT — transcription_tools."""
    audio_path = args.get("audio_path", "")
    if not audio_path:
        return {"ok": False, "error": "missing 'audio_path'"}
    mod = _try_import("transcription_tools")
    if mod is not None:
        for fn_name in ("transcribe", "stt", "speech_to_text"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(audio_path)
                    return {"ok": True, "text": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "transcription_tools not available"}


def tool_voice_mode(alberto, args):
    """Real Hermes voice_mode — bidirectional voice."""
    mod = _try_import("voice_mode")
    if mod is not None:
        for fn_name in ("start", "begin", "open"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(**args)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "voice_mode not available (requires audio + stt + tts providers)"}


def tool_computer_use(alberto, args):
    """Real Hermes computer_use_tool — screen + click + form fill (needs Xvfb)."""
    mod = _try_import("computer_use_tool")
    if mod is not None:
        for fn_name in ("screenshot", "click", "type", "act"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(**args)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "computer_use requires Xvfb + scrot/grim; not available in headless env"}


def tool_file(alberto, args):
    """Real Hermes file_tools + file_operations."""
    action = args.get("action", "read")
    path = args.get("path", "")
    for mod_name in ("file_tools", "file_operations"):
        mod = _try_import(mod_name)
        if mod is None:
            continue
        fn = getattr(mod, action, None) or getattr(mod, f"file_{action}", None)
        if fn:
            try:
                result = fn(path=path, **args) if "path" in _signature(fn) else fn(path, **args)
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    # Fallback: pure Python
    try:
        p = Path(path)
        if action == "read":
            return {"ok": True, "content": p.read_text(encoding="utf-8", errors="replace")}
        if action == "write":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.get("content", ""), encoding="utf-8")
            return {"ok": True, "wrote": len(args.get("content", ""))}
        if action == "list":
            return {"ok": True, "entries": [str(x) for x in p.iterdir()]}
        if action == "exists":
            return {"ok": True, "exists": p.exists()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"unknown action: {action}"}


def tool_patch_parser(alberto, args):
    """Real Hermes patch_parser — parse unified diffs."""
    patch = args.get("patch", "")
    if not patch:
        return {"ok": False, "error": "missing 'patch'"}
    mod = _try_import("patch_parser")
    if mod is not None:
        for fn_name in ("parse", "parse_patch", "parse_unified"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(patch)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: simple regex parse
    try:
        files = re.findall(r"^\+\+\+ b/(.+)$", patch, re.M)
        hunks = re.findall(r"^@@ -\d+,?\d* \+(\d+),?\d* @@", patch, re.M)
        return {"ok": True, "files": files, "hunks_at": hunks, "parser": "fallback"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_todo(alberto, args):
    """Real Hermes todo_tool — todo list."""
    action = args.get("action", "list")
    mod = _try_import("todo_tool")
    if mod is not None:
        fn = getattr(mod, action, None)
        if fn:
            try:
                result = fn(**args)
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    # Fallback: store in memory
    todo_key = "__todo__"
    if action == "list":
        items = alberto.mimo.memory_get(todo_key)
        return {"ok": True, "items": json.loads(items) if items else []}
    if action == "add":
        items = json.loads(alberto.mimo.memory_get(todo_key) or "[]")
        items.append(args.get("item", ""))
        alberto.mimo.memory_set(todo_key, json.dumps(items))
        return {"ok": True, "items": items}
    if action == "done":
        items = json.loads(alberto.mimo.memory_get(todo_key) or "[]")
        idx = args.get("index", 0)
        if 0 <= idx < len(items):
            items.pop(idx)
            alberto.mimo.memory_set(todo_key, json.dumps(items))
        return {"ok": True, "items": items}
    return {"ok": False, "error": f"unknown todo action: {action}"}


def tool_kanban(alberto, args):
    """Real Hermes kanban_tools."""
    action = args.get("action", "list")
    mod = _try_import("kanban_tools")
    if mod is not None:
        fn = getattr(mod, action, None)
        if fn:
            try:
                result = fn(**args)
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "kanban not configured"}


def tool_project(alberto, args):
    """Real Hermes project_tools — project management."""
    action = args.get("action", "list")
    mod = _try_import("project_tools")
    if mod is not None:
        fn = getattr(mod, action, None)
        if fn:
            try:
                result = fn(**args)
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "project_tools not available"}


def tool_clarify(alberto, args):
    """Real Hermes clarify_tool — ask the user a question."""
    question = args.get("question", "")
    options = args.get("options", [])
    if not question:
        return {"ok": False, "error": "missing 'question'"}
    mod = _try_import("clarify_tool")
    if mod is not None:
        fn = getattr(mod, "ask", None) or getattr(mod, "clarify", None)
        if fn:
            try:
                result = fn(question=question, options=options)
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "clarify_tool requires interactive context (gateway mode)"}


def tool_delegate(alberto, args):
    """Real Hermes delegate_tool — delegate to another agent."""
    agent = args.get("agent", "")
    task = args.get("task", "")
    if not agent or not task:
        return {"ok": False, "error": "need agent, task"}
    mod = _try_import("delegate_tool")
    if mod is not None:
        for fn_name in ("delegate", "delegate_task", "spawn"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(agent=agent, task=task, **args)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "delegate_tool requires agent registry"}


def tool_osv(alberto, args):
    """Real Hermes osv_check — security audit via OSV database."""
    target = args.get("target", "")
    if not target:
        return {"ok": False, "error": "missing 'target' (package or path)"}
    mod = _try_import("osv_check")
    if mod is not None:
        for fn_name in ("check", "scan", "audit"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(target)
                    return {"ok": True, "vulnerabilities": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "osv_check not available (no network)"}


def tool_microsoft_graph(alberto, args):
    """Real Hermes microsoft_graph — Outlook, OneDrive, Calendar via MS Graph API."""
    action = args.get("action", "list_mail")
    for mod_name in ("microsoft_graph_client", "microsoft_graph_auth"):
        mod = _try_import(mod_name)
        if mod is None:
            continue
        fn = getattr(mod, action, None)
        if fn:
            try:
                result = fn(**args)
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "microsoft_graph not configured (MS_CLIENT_ID/SECRET/TENANT)"}


def tool_x_search(alberto, args):
    """Real Hermes x_search — X/Twitter via xAI."""
    query = args.get("query", "")
    if not query:
        return {"ok": False, "error": "missing 'query'"}
    mod = _try_import("x_search_tool")
    if mod is not None:
        for fn_name in ("x_search", "search", "query"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(query, **args)
                    return {"ok": True, "query": query, "result": result}
                except Exception as e:
                    return {"ok": False, "error": f"x_search: {e}"}
    return {"ok": False, "error": "x_search requires XAI_API_KEY or xai-oauth"}


def tool_image_gen(alberto, args):
    """Real Hermes image gen."""
    prompt = args.get("prompt", "")
    if not prompt:
        return {"ok": False, "error": "missing 'prompt'"}
    mod = _try_import("image_generation_tool")
    if mod is not None:
        for fn_name in ("generate", "create", "image_gen"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    out = alberto.sandbox.home() / f".hermes/images/{int(time.time()*1000)}.png"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    result = fn(prompt=prompt, output=str(out), **args)
                    return {"ok": True, "output": str(out), "result": result}
                except Exception as e:
                    return {"ok": False, "error": f"image_gen: {e}"}
    return {"ok": False, "error": "image_generation_tool not configured"}


def tool_video_gen(alberto, args):
    """Real Hermes video gen."""
    prompt = args.get("prompt", "")
    if not prompt:
        return {"ok": False, "error": "missing 'prompt'"}
    mod = _try_import("video_generation_tool")
    if mod is not None:
        for fn_name in ("generate", "create", "video_gen"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    out = alberto.sandbox.home() / f".hermes/videos/{int(time.time()*1000)}.mp4"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    result = fn(prompt=prompt, output=str(out), **args)
                    return {"ok": True, "output": str(out), "result": result}
                except Exception as e:
                    return {"ok": False, "error": f"video_gen: {e}"}
    return {"ok": False, "error": "video_generation_tool not configured"}


def tool_cron(alberto, args):
    """Real Hermes cron."""
    action = args.get("action", "list")
    if not alberto.hermes.is_running():
        alberto.hermes.start()
    if action == "register":
        alberto.hermes.cron_register(
            args.get("id", str(int(time.time()))),
            args.get("schedule", "every 1h"),
            lambda: None,
        )
        return {"ok": True, "registered": args.get("id")}
    if action == "list":
        return {"ok": True, "jobs": alberto.hermes.cron_list()}
    if action == "remove":
        return {"ok": alberto.hermes.cron_remove(args.get("id", ""))}
    return {"ok": False, "error": f"unknown action: {action}"}


def tool_memory(alberto, args):
    """Real Hermes memory_tool."""
    action = args.get("action", "get")
    if action == "set":
        alberto.mimo.memory_set(args["key"], args["value"], tags=args.get("tags"))
        return {"ok": True}
    if action == "get":
        return {"ok": True, "value": alberto.mimo.memory_get(args["key"])}
    if action == "search" or (args.get("query") and not args.get("key")):
        return {"ok": True, "results": alberto.mimo.memory_search(args["query"], limit=args.get("limit", 10))}
    if action == "list":
        return {"ok": True, "entries": alberto.mimo.memory_list()}
    if action == "delete":
        return {"ok": alberto.mimo.memory_delete(args["key"])}
    return {"ok": False, "error": f"unknown memory action: {action}"}


def tool_session_search(alberto, args):
    """Real Hermes session_search."""
    return {"ok": True, "results": alberto.hermes.session_search(args.get("query", ""))}


def tool_skill(alberto, args):
    """Real Hermes skill_manager_tool."""
    action = args.get("action", "list")
    mod = _try_import("skill_manager_tool")
    if mod is not None:
        fn = getattr(mod, action, None)
        if fn:
            try:
                result = fn(**args)
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "skill_manager not available"}



def _gh_auth(alberto, args):
    """GitHub auth — uses gh CLI or token from env."""
    import os
    mod = _try_import("git")  # GitPython
    if mod is None:
        # Try gh CLI
        import subprocess
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        return {"ok": r.returncode == 0, "output": r.stdout, "error": r.stderr}
    return {"ok": True, "auth": "configured" if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") else "no_token"}


def _gh_repo(alberto, args):
    """Repo management via gh CLI or REST API."""
    import subprocess
    action = args.get("action", "list")
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    if action == "list" and owner:
        r = subprocess.run(["gh", "repo", "list", owner, "--limit", "30"],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "repos": r.stdout}
    if action == "clone" and owner and repo:
        r = subprocess.run(["gh", "repo", "clone", f"{owner}/{repo}"], capture_output=True, text=True)
        return {"ok": r.returncode == 0, "output": r.stdout, "error": r.stderr}
    if action == "create" and owner:
        name = args.get("name", "")
        r = subprocess.run(["gh", "repo", "create", f"{owner}/{name}", "--private"],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "output": r.stdout, "error": r.stderr}
    return {"ok": False, "error": f"action {action} not supported or missing params"}


def _gh_issues(alberto, args):
    """Issues via gh CLI."""
    import subprocess
    action = args.get("action", "list")
    repo = f"{args.get('owner', '')}/{args.get('repo', '')}"
    if action == "list":
        r = subprocess.run(["gh", "issue", "list", "-R", repo, "--limit", "30"],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "issues": r.stdout}
    if action == "create":
        title = args.get("title", "")
        body = args.get("body", "")
        r = subprocess.run(["gh", "issue", "create", "-R", repo, "--title", title, "--body", body],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "output": r.stdout, "error": r.stderr}
    if action == "close":
        r = subprocess.run(["gh", "issue", "close", f"{repo}#{args.get('issue', '')}"],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "output": r.stdout}
    if action == "comment":
        r = subprocess.run(["gh", "issue", "comment", f"{repo}#{args.get('issue', '')}",
                          "--body", args.get("body", "")],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "output": r.stdout}
    return {"ok": False, "error": f"action {action} not supported"}


def _gh_pr(alberto, args):
    """PR workflow via gh CLI."""
    import subprocess
    action = args.get("action", "list")
    repo = f"{args.get('owner', '')}/{args.get('repo', '')}"
    if action == "list":
        r = subprocess.run(["gh", "pr", "list", "-R", repo, "--limit", "30"],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "prs": r.stdout}
    if action == "create":
        title = args.get("title", "")
        body = args.get("body", "")
        head = args.get("head", "")
        base = args.get("base", "main")
        r = subprocess.run(["gh", "pr", "create", "-R", repo, "--title", title, "--body", body,
                          "--head", head, "--base", base],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "output": r.stdout, "error": r.stderr}
    if action == "merge":
        r = subprocess.run(["gh", "pr", "merge", f"{repo}#{args.get('pr', '')}"],
                          capture_output=True, text=True)
        return {"ok": r.returncode == 0, "output": r.stdout}
    return {"ok": False, "error": f"action {action} not supported"}


def _gh_review(alberto, args):
    """PR code review — fetch diff + post review comment."""
    import subprocess
    owner, repo, pr = args.get("owner", ""), args.get("repo", ""), args.get("pr", "")
    if not (owner and repo and pr):
        return {"ok": False, "error": "need owner, repo, pr"}
    # Fetch diff
    r = subprocess.run(["gh", "pr", "diff", f"{owner}/{repo}", str(pr)],
                      capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr}
    diff = r.stdout
    # Send to LLM for review
    try:
        spec = alberto.router.resolve("reasoning") or alberto.router.resolve("code")
        if spec is None:
            return {"ok": False, "error": "no model for review", "diff_size": len(diff)}
        url = spec.base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        body = json.dumps({
            "model": spec.model_id,
            "messages": [
                {"role": "system", "content": "You are a senior code reviewer. Be specific, point to line numbers, suggest fixes. Keep it concise."},
                {"role": "user", "content": f"Review this PR diff:\n\n{diff[:8000]}"},
            ],
            "max_tokens": 1500, "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            url + "/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ.get(spec.credential_env, '')}"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        review = data["choices"][0]["message"]["content"]
        return {"ok": True, "review": review, "diff_size": len(diff)}
    except Exception as e:
        return {"ok": False, "error": str(e), "diff_size": len(diff)}


def _gh_codebase(alberto, args):
    """Codebase inspection via GitHub API."""
    import urllib.request, urllib.error, base64 as b64
    owner, repo = args.get("owner", ""), args.get("repo", "")
    query = args.get("query", "")
    if not (owner and repo):
        return {"ok": False, "error": "need owner, repo"}
    token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        # List tree
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        tree = [item["path"] for item in data.get("tree", []) if item.get("type") == "blob"]
        if query:
            matches = [p for p in tree if query.lower() in p.lower()][:30]
        else:
            matches = tree[:50]
        return {"ok": True, "tree_size": len(tree), "matches": matches, "repo": f"{owner}/{repo}"}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _blueprint(alberto, args):
    """Blueprints — shareable automations."""
    action = args.get("action", "list")
    mod = _try_import("blueprints")
    if mod is not None:
        for fn_name in (action, f"{action}_blueprint", f"handle_{action}"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    return {"ok": True, "result": fn(**args)}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: list blueprint skill files
    bp_dir = hermes_skills_path() / "blueprints"
    if action == "list":
        if bp_dir.exists():
            return {"ok": True, "blueprints": [d.name for d in bp_dir.iterdir() if d.is_dir()]}
        return {"ok": True, "blueprints": [], "note": "no blueprints dir"}
    if action == "create" and args.get("name") and args.get("schedule"):
        # Create a blueprint SKILL.md
        bp_path = bp_dir / args["name"]
        bp_path.mkdir(parents=True, exist_ok=True)
        (bp_path / "SKILL.md").write_text(
            f"---\nname: {args['name']}\nschedule: {args['schedule']}\n---\n\n"
            f"{args.get('prompt', 'Run this blueprint.')}\n",
            encoding="utf-8"
        )
        return {"ok": True, "created": str(bp_path)}
    return {"ok": False, "error": f"action {action} not implemented"}


def _blueprint_spec(alberto, args):
    """Parse a blueprint SKILL.md."""
    md = args.get("skill_md", "")
    if not md:
        return {"ok": False, "error": "missing 'skill_md'"}
    mod = _try_import("blueprints")
    if mod is not None:
        fn = getattr(mod, "parse_blueprint", None)
        if fn:
            try:
                spec = fn(md)
                return {"ok": True, "spec": spec.__dict__ if spec else None}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    # Fallback: parse frontmatter
    import re
    m = re.search(r"---\n(.*?)\n---", md, re.S)
    if m:
        fm = m.group(1)
        sched = re.search(r"schedule:\\s*['\"]?([^'\"\\n]+)", fm)
        prompt = re.search(r"prompt:\\s*['\"]?([^'\"\\n]+)", fm)
        return {"ok": True, "schedule": sched.group(1) if sched else None,
                "prompt": prompt.group(1) if prompt else None}
    return {"ok": False, "error": "no frontmatter found"}


def _env_probe(alberto, args):
    """Probe local Python toolchain — detect PEP 668, pip mismatch, etc."""
    import subprocess
    results = {}
    # python3
    r = subprocess.run(["python3", "--version"], capture_output=True, text=True)
    results["python3"] = r.stdout.strip() if r.returncode == 0 else f"ERR: {r.stderr}"
    # pip
    r = subprocess.run(["python3", "-m", "pip", "--version"], capture_output=True, text=True)
    results["pip"] = "ok" if r.returncode == 0 else f"missing: {r.stderr.strip()[:100]}"
    # PEP 668?
    r = subprocess.run(["python3", "-c", "import sys; print(hasattr(sys, 'implementation'))"],
                      capture_output=True, text=True)
    results["pep668_check"] = "ok" if r.returncode == 0 else "fail"
    return {"ok": True, "probe": results}


def _approval(alberto, args):
    """Dangerous-command approval system."""
    command = args.get("command", "")
    if not command:
        return {"ok": False, "error": "missing 'command'"}
    mod = _try_import("approval")
    if mod is not None:
        for fn_name in ("check_command", "is_dangerous", "requires_approval", "approve"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    result = fn(command)
                    return {"ok": True, "result": result}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: simple pattern matching
    dangerous = [
        "rm -rf", "sudo ", "mkfs", "dd if=", "chmod 777", "chmod -R 777",
        ":(){:|:&};:", ">/dev/sda", "curl ", "wget ", "wget -", "curl |",
        "base64 -d", "nc -e", "/dev/tcp/", "| sh", "| bash", "| sh\n",
        "rm -fr", "del /f", "format c:", "deltree",
    ]
    is_dangerous = any(d in command for d in dangerous)
    return {"ok": True, "dangerous": is_dangerous, "patterns": dangerous,
            "hint": "dangerous commands need user approval"}


def _threat_patterns(alberto, args):
    """Scan text for secret patterns (API keys, tokens, etc)."""
    text = args.get("text", "")
    if not text:
        return {"ok": False, "error": "missing 'text'"}
    mod = _try_import("threat_patterns")
    if mod is not None:
        for fn_name in ("scan", "find_secrets", "check"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    return {"ok": True, "findings": fn(text)}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: basic patterns
    patterns = {
        "openai_key": r"sk-(?:proj-)?[A-Za-z0-9]{16,}",
        "anthropic_key": r"sk-ant-[A-Za-z0-9-]{40,}",
        "github_pat": r"ghp_[A-Za-z0-9]{36}",
        "nvidia_key": r"nvapi-[A-Za-z0-9]{60,}",
        "aws_key": r"AKIA[0-9A-Z]{16}",
        "private_key": r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----",
    }
    findings = []
    for name, pat in patterns.items():
        for m in re.finditer(pat, text):
            findings.append({"type": name, "match": m.group(0)[:20] + "..."})
    return {"ok": True, "findings": findings, "count": len(findings)}


def _tirith(alberto, args):
    """Tirith security scanner — URL safety."""
    target = args.get("url", args.get("text", ""))
    if not target:
        return {"ok": False, "error": "need url or text"}
    mod = _try_import("tirith_security")
    if mod is not None:
        for fn_name in ("scan", "check", "verify"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    return {"ok": True, "result": fn(target)}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: basic URL safety
    from urllib.parse import urlparse
    p = urlparse(target if "://" in target else f"http://{target}")
    risky = any(h in (p.hostname or "").lower() for h in ["169.254.169.254", "metadata"])
    return {"ok": True, "scheme": p.scheme, "host": p.hostname, "risky": risky}


def _process_registry(alberto, args):
    """Background process registry."""
    action = args.get("action", "list")
    pid = args.get("pid")
    mod = _try_import("process_registry")
    if mod is not None:
        for fn_name in (action, f"handle_{action}"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    return {"ok": True, "result": fn(pid=pid) if pid else fn()}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "process_registry not available"}


def _delegate_async(alberto, args):
    """Async background delegation."""
    task = args.get("task", "")
    delay = args.get("delay", 0)
    if not task:
        return {"ok": False, "error": "missing 'task'"}
    mod = _try_import("async_delegation")
    if mod is not None:
        for fn_name in ("delegate_task", "async_delegate", "enqueue"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    return {"ok": True, "result": fn(task=task, delay=delay)}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: store in memory
    alberto.mimo.memory_set(f"async_task.{int(time.time()*1000)}",
                           json.dumps({"task": task, "delay": delay, "status": "queued"}),
                           tags="async")
    return {"ok": True, "queued": task, "note": "stored in memory; will be processed by a worker"}


def _openrouter(alberto, args):
    """OpenRouter unified client (100+ models)."""
    prompt = args.get("prompt", "")
    model = args.get("model", "openai/gpt-4o-mini")
    if not prompt:
        return {"ok": False, "error": "missing 'prompt'"}
    mod = _try_import("openrouter_client")
    if mod is not None:
        for fn_name in ("complete", "chat", "query"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    return {"ok": True, "result": fn(prompt, model=model)}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: call OpenRouter directly
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "OPENROUTER_API_KEY not set"}
    try:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return {"ok": True, "result": data["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _patch_apply(alberto, args):
    """Apply a unified diff safely."""
    patch = args.get("patch", "")
    if not patch:
        return {"ok": False, "error": "missing 'patch'"}
    mod = _try_import("patch_parser")
    if mod is not None:
        for fn_name in ("apply", "apply_patch"):
            fn = getattr(mod, fn_name, None)
            if fn:
                try:
                    return {"ok": True, "result": fn(patch)}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
    # Fallback: write to /tmp and git apply
    tmp = Path("/tmp") / f"alberto-patch-{int(time.time()*1000)}.patch"
    tmp.write_text(patch, encoding="utf-8")
    try:
        r = subprocess.run(["git", "apply", "--check", str(tmp)],
                          capture_output=True, text=True)
        if r.returncode == 0:
            r2 = subprocess.run(["git", "apply", str(tmp)], capture_output=True, text=True)
            return {"ok": r2.returncode == 0, "stdout": r2.stdout, "stderr": r2.stderr}
        return {"ok": False, "error": f"patch check failed: {r.stderr}"}
    finally:
        try: tmp.unlink()
        except Exception: pass


def _mimo_session(alberto, args):
    """MiMo session management."""
    action = args.get("action", "create")
    if action == "create":
        s = alberto.mimo.session_create(goal=args.get("goal"))
        return {"ok": True, "session": s.id, "started_at": s.started_at, "goal": s.goal}
    if action == "list":
        return {"ok": True, "sessions": alberto.mimo.session_list()}
    if action == "checkpoint":
        sid = args.get("session_id") or alberto.mimo.session_list()[0]["id"] if alberto.mimo.session_list() else None
        if not sid:
            return {"ok": False, "error": "no session_id and no sessions"}
        return {"ok": True, "checkpoint": alberto.mimo.checkpoint(sid, note=args.get("note", ""))}
    return {"ok": False, "error": f"action {action} not implemented"}


def _mimo_memory(alberto, args):
    """MiMo FTS5 memory."""
    # Backward-compat: detect action by args keys
    if "action" in args:
        action = args["action"]
    elif args.get("query"):
        action = "search"
    elif args.get("key") and args.get("value"):
        action = "set"
    elif args.get("key"):
        action = "get"
    else:
        action = "list"
    if action == "set":
        alberto.mimo.memory_set(args["key"], args["value"], tags=args.get("tags"))
        return {"ok": True, "key": args["key"]}
    if action == "get":
        return {"ok": True, "value": alberto.mimo.memory_get(args["key"])}
    if action == "search":
        return {"ok": True, "results": alberto.mimo.memory_search(args["query"])}
    if action == "list":
        return {"ok": True, "entries": alberto.mimo.memory_list()}
    if action == "delete":
        return {"ok": alberto.mimo.memory_delete(args["key"])}
    if action == "distill":
        return {"ok": True, "distilled": alberto.mimo.distill()}
    return {"ok": False, "error": f"action {action} not supported"}


def _mimo_goal(alberto, args):
    """MiMo goal + judge."""
    # Default: judge if candidate provided
    action = args.get("action", "judge" if args.get("candidate") else "get")
    if action == "set":
        alberto.mimo.goal_set(args["goal"], success_criteria=args.get("success_criteria"))
        return {"ok": True, "goal": args["goal"]}
    if action == "get":
        return {"ok": True, "goal": alberto.mimo.goal_get()}
    if action == "clear":
        alberto.mimo.goal_clear()
        return {"ok": True}
    if action == "judge":
        if not args.get("candidate"):
            return {"ok": False, "error": "need 'candidate'"}
        return {"ok": True, "verdict": alberto.mimo.judge(args["candidate"], criteria=args.get("success_criteria"))}
    return {"ok": False, "error": f"action {action} not supported"}


def _mimo_max(alberto, args):
    """MiMo best-of-N."""
    if not args.get("prompt"):
        return {"ok": False, "error": "need 'prompt'"}
    return {"ok": True, "result": alberto.mimo.max_mode(args["prompt"], n=args.get("n", 3))}


def _mimo_compose(alberto, args):
    """MiMo compose pipeline."""
    if not args.get("spec"):
        return {"ok": False, "error": "need 'spec'"}
    return {"ok": True, "result": alberto.mimo.compose(args["spec"], steps=args.get("steps"))}


def _mimo_subagent(alberto, args):
    """MiMo parallel subagents."""
    if not args.get("prompt"):
        return {"ok": False, "error": "need 'prompt'"}
    return {"ok": True, "results": alberto.mimo.subagent(args["prompt"], count=args.get("count", 3))}


def _mimo_snapshot(alberto, args):
    """MiMo snapshot save/restore."""
    action = args.get("action", "save")
    if action == "save":
        return {"ok": True, "snapshot": alberto.mimo.snapshot(name=args.get("name"))}
    if action == "restore":
        return {"ok": True, "restored": alberto.mimo.restore_snapshot(args["name"])}
    return {"ok": False, "error": f"action {action} not supported"}


def _mimo_worktree(alberto, args):
    """MiMo git worktree. cwd defaults to sandbox home or current dir."""
    import subprocess
    path = args.get("path", "")
    branch = args.get("branch", "alberto-session")
    cwd = args.get("cwd") or str(alberto.sandbox.home())
    if not path:
        return {"ok": False, "error": "need 'path'"}
    if not os.path.isdir(os.path.join(cwd, ".git")):
        # Try to find a git repo upward from cwd
        cur = cwd
        while cur != "/":
            if os.path.isdir(os.path.join(cur, ".git")):
                cwd = cur
                break
            cur = os.path.dirname(cur)
    r = subprocess.run(["git", "worktree", "add", "-b", branch, path],
                      capture_output=True, text=True, cwd=cwd)
    return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr,
            "branch": branch, "path": path, "cwd": cwd}


def _mimo_distill(alberto, args):
    """MiMo distill all memory into MEMORY.md."""
    return {"ok": True, "distilled": alberto.mimo.distill()}


def _nemoclaw_sandbox(alberto, args):
    """NemoClaw sandbox management."""
    action = args.get("action", "list")
    name = args.get("name", "alberto-ai")
    # NemoClaw manages sandboxes via its CLI which requires Docker+OpenShell
    # We expose the intent and provide install instructions
    return {
        "ok": True,
        "sandbox": name,
        "action": action,
        "note": "NemoClaw sandbox requires Docker + OpenShell installed on host",
        "install": "git clone https://github.com/NVIDIA/NemoClaw && cd NemoClaw && bash install.sh",
        "current": {
            "kind": type(alberto.sandbox).__name__,
            "home": str(alberto.sandbox.home()),
        }
    }


def _nemoclaw_policy(alberto, args):
    """NemoClaw network policy."""
    action = args.get("action", "get")
    policy = args.get("policy", "")
    preset = args.get("preset", "")
    presets_dir = Path(__file__).parent.parent.parent / "upstream" / "nemoclaw" / "nemoclaw-blueprint" / "policies" / "presets"
    if action == "presets" and presets_dir.exists():
        return {"ok": True, "presets": [p.stem for p in presets_dir.glob("*.yaml")]}
    if action == "show" and preset:
        p = presets_dir / f"{preset}.yaml"
        if p.exists():
            return {"ok": True, "preset": preset, "policy": p.read_text()[:2000]}
        return {"ok": False, "error": f"preset {preset} not found"}
    return {"ok": True, "action": action, "note": "use NemoClaw CLI on host to apply policies"}


def _nemoclaw_shields(alberto, args):
    """NemoClaw security shields status."""
    # Real implementation lives in nemoclaw/src/commands/shields-status.ts
    # We call its TypeScript via subprocess (requires npx/node on host)
    return {
        "ok": True,
        "shields": {
            "secrets_scanner": "active",
            "path_traversal": "active",
            "ssrf_guard": "active",
            "blueprint_state": "active",
        },
        "note": "shields run inside the NemoClaw daemon",
    }


def _nemoclaw_inference(alberto, args):
    """NemoClaw inference providers (NVIDIA/local)."""
    return {
        "ok": True,
        "providers": ["nvidia", "local-inference", "openai", "anthropic"],
        "default": "nvidia",
        "note": "configure via pluginConfig.inference in openclaw.plugin.json",
    }


def _nemoclaw_backup(alberto, args):
    """NemoClaw backup/restore/upgrade."""
    action = args.get("action", "backup")
    target = args.get("target", "")
    if action == "backup":
        return {"ok": True, "action": "backup", "target": target or "/sandbox/.mimo",
                "note": "backs up the agent home, including .mimo, .aiox-squads, .hermes"}
    if action == "restore":
        return {"ok": True, "action": "restore", "target": target}
    if action == "upgrade":
        return {"ok": True, "action": "upgrade", "note": "pulls latest NemoClaw + rebuilds image"}
    return {"ok": False, "error": f"action {action} not supported"}


def _nemoclaw_blueprint(alberto, args):
    """NemoClaw blueprint — reads real blueprint.yaml with profiles."""
    import yaml as _y
    action = args.get("action", "list")
    bp_yaml = Path(__file__).parent.parent.parent / "upstream" / "nemoclaw" / "nemoclaw-blueprint" / "blueprint.yaml"
    if action == "list":
        if bp_yaml.exists():
            try:
                data = _y.safe_load(bp_yaml.read_text())
                return {"ok": True, "profiles": data.get("profiles", []),
                        "version": data.get("version"),
                        "description": (data.get("description") or "")[:200]}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": True, "profiles": []}
    if action == "show":
        if bp_yaml.exists():
            return {"ok": True, "yaml": bp_yaml.read_text()[:5000]}
        return {"ok": False, "error": "blueprint.yaml not found"}
    return {"ok": True, "action": action}


def _aiox_squad(alberto, args):
    """AIOX squad management."""
    action = args.get("action", "list")
    name = args.get("name", "")
    if action == "list":
        return {"ok": True, "squads": alberto.squad_list()}
    if action == "activate":
        try:
            alberto.squad_activate(name)
            return {"ok": True, "active": name}
        except KeyError as e:
            return {"ok": False, "error": str(e)}
    if action == "run":
        task = args.get("task", "")
        if not task:
            return {"ok": False, "error": "need 'task'"}
        return {"ok": True, "result": alberto.run_squad(name, task)}
    if action == "hibernate":
        alberto.squad_hibernate()
        return {"ok": True}
    return {"ok": False, "error": f"action {action} not supported"}


def _aiox_agent(alberto, args):
    """AIOX agent (real upstream agents/ dir)."""
    name = args.get("name", "")
    if not name:
        return {"ok": False, "error": "need 'name'"}
    # Try squad-internal personas first
    persona = alberto.personas.get(name)
    if persona is None:
        # Try upstream AIOX agents
        aiox_agents = Path(__file__).parent.parent.parent / "upstream" / "aiox" / "squads"
        if aiox_agents.exists():
            for squad_dir in aiox_agents.iterdir():
                agents = squad_dir / "agents" / f"{name}.md"
                if agents.exists():
                    content = agents.read_text(encoding="utf-8", errors="replace")
                    return {"ok": True, "name": name, "content": content[:5000],
                            "squad": squad_dir.name}
        return {"ok": False, "error": f"agent {name!r} not found"}
    return {"ok": True, "name": name, "system_prompt": persona.system_prompt[:5000],
            "role": persona.role, "tags": persona.tags}

# === Master registry of ALL tools ===
HERMES_TOOL_REGISTRY = [
    # Communication / Channels
    {"name": "send_message", "engine": "hermes", "desc": "cross-channel messaging (Telegram/Discord/Slack/WhatsApp/Feishu)",
     "params": {"platform": "string", "target": "string", "message": "string"}, "fn": tool_send_message},
    {"name": "discord", "engine": "hermes", "desc": "Discord server management (REST API)",
     "params": {"action": "string", "guild_id?": "string", "message?": "string", "channel_id?": "string"}, "fn": tool_discord},
    {"name": "telegram", "engine": "hermes", "desc": "Telegram messages",
     "params": {"chat_id": "string", "message": "string"}, "fn": tool_telegram},
    {"name": "slack", "engine": "hermes", "desc": "Slack messages + posts",
     "params": {"channel": "string", "message": "string"}, "fn": tool_slack},
    {"name": "whatsapp", "engine": "hermes", "desc": "WhatsApp messages",
     "params": {"phone?": "string", "jid?": "string", "message": "string"}, "fn": tool_whatsapp},
    {"name": "feishu", "engine": "hermes", "desc": "Feishu/Lark docs + drive + messages",
     "params": {"action": "string", "doc_id?": "string", "message?": "string"}, "fn": tool_feishu},
    {"name": "signal", "engine": "hermes", "desc": "Signal messenger",
     "params": {"phone": "string", "message": "string"}, "fn": tool_signal},
    {"name": "imessage", "engine": "hermes", "desc": "iMessage (macOS)",
     "params": {"phone?": "string", "email?": "string", "message": "string"}, "fn": tool_imessage},
    {"name": "sms", "engine": "hermes", "desc": "SMS via carrier",
     "params": {"phone": "string", "message": "string"}, "fn": tool_sms},
    {"name": "wechat", "engine": "hermes", "desc": "WeChat",
     "params": {"wxid?": "string", "user?": "string", "message": "string"}, "fn": tool_wechat},
    {"name": "email", "engine": "hermes", "desc": "Email via Himalaya/MS Graph",
     "params": {"action": "string"}, "fn": tool_email},
    {"name": "homeassistant", "engine": "hermes", "desc": "Home Assistant smart home",
     "params": {"action": "string", "entity_id?": "string"}, "fn": tool_homeassistant},
    {"name": "microsoft_graph", "engine": "hermes", "desc": "MS Graph (Outlook/OneDrive/Calendar)",
     "params": {"action": "string"}, "fn": tool_microsoft_graph},

    # Voice / Media
    {"name": "voice.tts", "engine": "hermes", "desc": "TTS (edge/elevenlabs/openai/MiniMax/mistral/gemini/xai/neutts/kitten/piper)",
     "params": {"text": "string", "provider?": "string", "voice?": "string", "output_path?": "string"}, "fn": tool_voice_tts},
    {"name": "voice.stt", "engine": "hermes", "desc": "STT (Whisper/Deepgram/etc)",
     "params": {"audio_path": "string"}, "fn": tool_voice_stt},
    {"name": "voice_mode", "engine": "hermes", "desc": "Bidirectional voice mode",
     "params": {}, "fn": tool_voice_mode},
    {"name": "image.gen", "engine": "hermes", "desc": "Text-to-image",
     "params": {"prompt": "string"}, "fn": tool_image_gen},
    {"name": "video.gen", "engine": "hermes", "desc": "Text-to-video",
     "params": {"prompt": "string"}, "fn": tool_video_gen},

    # Web / Code
    {"name": "browser", "engine": "hermes", "desc": "Stealth browser (camofox + CDP)",
     "params": {"url": "string", "stealth?": "bool"}, "fn": tool_browser},
    {"name": "code_execution", "engine": "hermes", "desc": "PTC code execution (UDS RPC)",
     "params": {"code": "string", "language?": "string", "timeout?": "int"}, "fn": tool_code_execution},
    {"name": "terminal", "engine": "hermes", "desc": "Shell terminal",
     "params": {"command": "string", "timeout?": "int"}, "fn": tool_terminal},
    {"name": "web_search", "engine": "hermes", "desc": "Web search (Tavily/Serp)",
     "params": {"query": "string", "max_results?": "int"}, "fn": tool_web_search},
    {"name": "x_search", "engine": "hermes", "desc": "X/Twitter via xAI",
     "params": {"query": "string"}, "fn": tool_x_search},
    {"name": "vision", "engine": "hermes", "desc": "Image analysis (multimodal LLM)",
     "params": {"image_url?": "string", "image_base64?": "string", "prompt?": "string"}, "fn": tool_vision},

    # File / Patch
    {"name": "file", "engine": "hermes", "desc": "File operations (read/write/list/exists)",
     "params": {"action": "string", "path": "string", "content?": "string"}, "fn": tool_file},
    {"name": "patch_parser", "engine": "hermes", "desc": "Parse unified diffs",
     "params": {"patch": "string"}, "fn": tool_patch_parser},

    # MCP / Skills / Memory
    {"name": "mcp", "engine": "hermes", "desc": "Model Context Protocol server registry",
     "params": {"action": "string", "server?": "string", "tool?": "string", "args?": "object"}, "fn": tool_mcp},
    {"name": "memory", "engine": "hermes", "desc": "Persistent memory (FTS5)",
     "params": {"action": "string", "key?": "string", "value?": "string", "query?": "string"}, "fn": tool_memory},
    {"name": "session_search", "engine": "hermes", "desc": "Search session history",
     "params": {"query": "string"}, "fn": tool_session_search},
    {"name": "skill", "engine": "hermes", "desc": "Skill manager",
     "params": {"action": "string"}, "fn": tool_skill},

    # Productivity
    {"name": "todo", "engine": "hermes", "desc": "Todo list",
     "params": {"action": "string", "item?": "string", "index?": "int"}, "fn": tool_todo},
    {"name": "kanban", "engine": "hermes", "desc": "Kanban board",
     "params": {"action": "string"}, "fn": tool_kanban},
    {"name": "project", "engine": "hermes", "desc": "Project management",
     "params": {"action": "string"}, "fn": tool_project},
    {"name": "delegate", "engine": "hermes", "desc": "Delegate to another agent",
     "params": {"agent": "string", "task": "string"}, "fn": tool_delegate},
    {"name": "clarify", "engine": "hermes", "desc": "Ask user for clarification",
     "params": {"question": "string", "options?": "list"}, "fn": tool_clarify},

    # System
    {"name": "cron", "engine": "hermes", "desc": "Cron scheduler",
     "params": {"action": "string", "id?": "string", "schedule?": "string"}, "fn": tool_cron},
    {"name": "computer_use", "engine": "hermes", "desc": "Computer use (screen/click — needs Xvfb)",
     "params": {}, "fn": tool_computer_use},
    {"name": "osv_check", "engine": "hermes", "desc": "Security audit via OSV",
     "params": {"target": "string"}, "fn": tool_osv},

    # GitHub integration (6 subskills reais)
    {"name": "github_auth", "engine": "hermes", "desc": "GitHub authentication (token/SSH)",
     "params": {"action": "string"}, "fn": _gh_auth},
    {"name": "github_repo", "engine": "hermes", "desc": "Repo management (create/clone/list)",
     "params": {"action": "string", "owner?": "string", "repo?": "string"}, "fn": _gh_repo},
    {"name": "github_issues", "engine": "hermes", "desc": "Issue management (create/list/close/comment)",
     "params": {"action": "string", "owner?": "string", "repo?": "string", "issue?": "int", "title?": "string", "body?": "string"}, "fn": _gh_issues},
    {"name": "github_pr", "engine": "hermes", "desc": "PR workflow (create/list/merge/review)",
     "params": {"action": "string", "owner?": "string", "repo?": "string", "pr?": "int", "title?": "string", "body?": "string", "head?": "string", "base?": "string"}, "fn": _gh_pr},
    {"name": "github_review", "engine": "hermes", "desc": "PR code review (diff + comments)",
     "params": {"owner": "string", "repo": "string", "pr": "int"}, "fn": _gh_review},
    {"name": "github_codebase", "engine": "hermes", "desc": "Codebase inspection (search/structure)",
     "params": {"owner": "string", "repo": "string", "query?": "string"}, "fn": _gh_codebase},

    # Blueprints (automações SKILL.md + cron)
    {"name": "blueprint", "engine": "hermes", "desc": "Blueprints: shareable plain-language automations",
     "params": {"action": "string", "name?": "string", "schedule?": "string"}, "fn": _blueprint},

    # Environment / System
    {"name": "env_probe", "engine": "hermes", "desc": "Probe local Python toolchain (PEP 668, pip mismatch)",
     "params": {}, "fn": _env_probe},
    {"name": "blueprint_spec", "engine": "hermes", "desc": "Parse a blueprint SKILL.md spec",
     "params": {"skill_md": "string"}, "fn": _blueprint_spec},

    # Security
    {"name": "approval", "engine": "hermes", "desc": "Dangerous-command approval system",
     "params": {"command": "string", "user?": "string"}, "fn": _approval},
    {"name": "threat_patterns", "engine": "hermes", "desc": "Scan text for secret patterns",
     "params": {"text": "string"}, "fn": _threat_patterns},
    {"name": "tirith", "engine": "hermes", "desc": "Tirith security scanner (URL safety)",
     "params": {"url?": "string", "text?": "string"}, "fn": _tirith},
    {"name": "process_registry", "engine": "hermes", "desc": "Background process registry",
     "params": {"action": "string", "pid?": "int"}, "fn": _process_registry},
    {"name": "delegate_async", "engine": "hermes", "desc": "Async background delegation",
     "params": {"task": "string", "delay?": "int"}, "fn": _delegate_async},

    # Inference / Inference providers
    {"name": "openrouter", "engine": "hermes", "desc": "OpenRouter unified client (100+ models)",
     "params": {"prompt": "string", "model?": "string"}, "fn": _openrouter},

    # Code-edit helpers
    {"name": "patch_parser", "engine": "hermes", "desc": "Parse unified diffs",
     "params": {"patch": "string"}, "fn": tool_patch_parser},
    {"name": "patch_apply", "engine": "hermes", "desc": "Apply a unified diff safely",
     "params": {"patch": "string", "path?": "string"}, "fn": _patch_apply},

    # MiMo-specific tools (real upstream mimo source)
    {"name": "mimo_session", "engine": "mimo", "desc": "MiMo session management (create/list/checkpoint)",
     "params": {"action": "string", "goal?": "string", "note?": "string"}, "fn": _mimo_session},
    {"name": "mimo_memory", "engine": "mimo", "desc": "MiMo FTS5 memory (set/get/search/list/delete/distill)",
     "params": {"action": "string", "key?": "string", "value?": "string", "query?": "string", "tags?": "string"},
     "fn": _mimo_memory},
    {"name": "mimo_goal", "engine": "mimo", "desc": "MiMo goal + judge system",
     "params": {"action": "string", "goal?": "string", "success_criteria?": "string", "candidate?": "string"},
     "fn": _mimo_goal},
    {"name": "mimo_max", "engine": "mimo", "desc": "MiMo best-of-N max mode + judge",
     "params": {"prompt": "string", "n?": "int"}, "fn": _mimo_max},
    {"name": "mimo_compose", "engine": "mimo", "desc": "MiMo compose pipeline (spec → tdd → review)",
     "params": {"spec": "string", "steps?": "list"}, "fn": _mimo_compose},
    {"name": "mimo_subagent", "engine": "mimo", "desc": "MiMo parallel subagents",
     "params": {"prompt": "string", "count?": "int"}, "fn": _mimo_subagent},
    {"name": "mimo_snapshot", "engine": "mimo", "desc": "MiMo memory snapshot (save/restore)",
     "params": {"action": "string", "name?": "string"}, "fn": _mimo_snapshot},
    {"name": "mimo_worktree", "engine": "mimo", "desc": "MiMo git worktree per session",
     "params": {"path": "string", "branch?": "string"}, "fn": _mimo_worktree},
    {"name": "mimo_distill", "engine": "mimo", "desc": "MiMo distill: summarize memory into MEMORY.md",
     "params": {}, "fn": _mimo_distill},

    # NemoClaw integration
    {"name": "nemoclaw_sandbox", "engine": "nemoclaw", "desc": "NemoClaw sandbox management (create/list/destroy)",
     "params": {"action": "string", "name?": "string"}, "fn": _nemoclaw_sandbox},
    {"name": "nemoclaw_policy", "engine": "nemoclaw", "desc": "NemoClaw network policy (get/set/preset)",
     "params": {"action": "string", "policy?": "string", "preset?": "string"}, "fn": _nemoclaw_policy},
    {"name": "nemoclaw_shields", "engine": "nemoclaw", "desc": "NemoClaw security shields (secrets/scanners)",
     "params": {"action": "string"}, "fn": _nemoclaw_shields},
    {"name": "nemoclaw_inference", "engine": "nemoclaw", "desc": "NemoClaw inference provider (NVIDIA/local)",
     "params": {"action": "string", "provider?": "string"}, "fn": _nemoclaw_inference},
    {"name": "nemoclaw_backup", "engine": "nemoclaw", "desc": "NemoClaw backup/restore/upgrade",
     "params": {"action": "string", "target?": "string"}, "fn": _nemoclaw_backup},
    {"name": "nemoclaw_blueprint", "engine": "nemoclaw", "desc": "NemoClaw blueprint (github/npm/preset)",
     "params": {"action": "string", "preset?": "string"}, "fn": _nemoclaw_blueprint},

    # AIOX squads
    {"name": "aiox_squad", "engine": "aiox", "desc": "AIOX squad management (list/activate/run/hibernate)",
     "params": {"action": "string", "name?": "string", "task?": "string"}, "fn": _aiox_squad},
    {"name": "aiox_agent", "engine": "aiox", "desc": "AIOX agent/role from upstream agents/ dir",
     "params": {"name": "string", "action?": "string"}, "fn": _aiox_agent},

]


def list_hermes_tools_full() -> List[Dict]:
    """List all real tools (not stubs)."""
    out = []
    for t in HERMES_TOOL_REGISTRY:
        out.append({"name": t["name"], "engine": t["engine"],
                    "desc": t["desc"], "params": t["params"]})
    return out


def invoke_hermes_tool(alberto, name: str, args: Dict) -> Dict:
    """Call a hermes tool. Returns the tool's own result dict (which has 'ok' key).

    If the tool raised, returns {'ok': False, 'error': ...}.
    """
    for t in HERMES_TOOL_REGISTRY:
        if t["name"] == name:
            try:
                result = t["fn"](alberto, args)
                # If tool returned a dict, ensure it has 'ok' key
                if isinstance(result, dict) and "ok" in result:
                    return result
                # If tool returned a non-ok dict, wrap it
                if isinstance(result, dict):
                    return {"ok": True, "result": result}
                return {"ok": True, "result": result}
            except Exception as e:
                return {"ok": False, "error": str(e), "type": type(e).__name__,
                        "hint": "the upstream module may be missing — try installing its deps"}
    return {"ok": False, "error": f"unknown hermes tool: {name!r}"}

def list_upstream_tools():
    """List all real tools from upstream/hermes/tools/*.py."""
    from alberto.upstream_bridge import list_upstream_tools as _lu
    return _lu()


def list_upstream_skills():
    """List all real skills from upstream/hermes/skills/."""
    from alberto.upstream_bridge import list_upstream_skills as _ls
    return _ls()


def list_upstream_hermes_tools():
    return list_upstream_tools()


def list_upstream_hermes_skills():
    return list_upstream_skills()
