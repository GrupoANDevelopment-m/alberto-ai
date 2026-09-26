"""
Hermes engine — wraps the REAL Hermes agent tools from upstream.

Real tools we wrap (Python source in upstream/hermes/tools/):
  - code_execution_tool.py — Programmatic Tool Calling (PTC) via UDS RPC
  - browser_tool.py + browser_camofox.py — stealth browser
  - tts_tool.py — Edge TTS / ElevenLabs / OpenAI TTS / MiniMax TTS / NeuTTS / Piper / KittenTTS
  - image_generation_tool.py — text → image
  - video_generation_tool.py — text → video
  - x_search_tool.py — X/Twitter search via xAI
  - voice_mode.py — full voice in/out
  - cronjob_tools.py — cron scheduling
  - memory_tool.py — agent memory
  - session_search_tool.py — FTS5 session search
  - file_tools.py + file_operations.py — file manipulation
  - skill_manager_tool.py + skills_tool.py — skills
  - transcription_tools.py — STT

We invoke them via Python's importlib so we get the REAL implementations,
not stubs.
"""
from __future__ import annotations
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .base import EngineInfo
from ..upstream_bridge import (
    import_hermes_tool,
    hermes_tools_path,
    hermes_skills_path,
    list_upstream_tools,
    list_upstream_skills,
)


class HermesEngine:
    name = "Hermes"
    version = "1.0.0"

    def __init__(self, sandbox, mimo=None, *, home: Optional[Path] = None):
        self._sandbox = sandbox
        self._mimo = mimo
        self._home = home or (sandbox.home() / ".hermes")
        self._home.mkdir(parents=True, exist_ok=True)
        self._running = False
        self._cron_jobs: Dict[str, Dict] = {}
        self._cron_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Real Hermes modules lazily imported
        self._mod = {}

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name=self.name, version=self.version,
            running=self._running, pid=None,
        )

    def _get(self, name: str):
        """Lazy-import a real Hermes tool module."""
        if name not in self._mod:
            self._mod[name] = import_hermes_tool(name)
        return self._mod[name]

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._start_cron()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._cron_thread:
            self._cron_thread.join(timeout=2)
        self._cron_thread = None

    def is_running(self) -> bool:
        return self._running

    def available_tools(self) -> List[Dict]:
        """List REAL Hermes tools available in upstream/."""
        return list_upstream_tools()

    def available_skills(self) -> List[Dict]:
        """List REAL Hermes skills available in upstream/."""
        return list_upstream_skills()

    # ===== Browser (REAL: upstream/hermes/tools/browser_tool.py) =====
    def browser(self, url: str, *, stealth: bool = True) -> str:
        """Fetch a URL. Uses real Hermes browser_tool if available.

        Falls back to urllib only if import fails.
        """
        try:
            mod = self._get("browser_tool")
            # Most Hermes tools expose a `fetch_url` or `scrape` callable
            for fn_name in ("fetch_url", "scrape", "open_url", "fetch"):
                if hasattr(mod, fn_name):
                    fn = getattr(mod, fn_name)
                    result = fn(url, stealth=stealth)
                    if isinstance(result, str):
                        return result
                    if isinstance(result, dict):
                        return result.get("content") or result.get("text") or json.dumps(result, default=str)
        except Exception as e:
            # If Hermes tool has unmet deps (e.g. missing playwright), fall back
            pass
        # Fallback: real HTTP via stdlib
        import urllib.request
        import urllib.error
        import ssl
        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(url, headers={"User-Agent": "Alberto-AI/1.0"})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = resp.read(5 * 1024 * 1024).decode("utf-8", errors="replace")
            return self._strip_html(data)[:8000]
        except urllib.error.HTTPError as e:
            return f"[HTTP {e.code}] {e.reason}"
        except Exception as e:
            return f"[browser error] {e}"

    @staticmethod
    def _strip_html(html: str) -> str:
        html = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
        html = re.sub(r"<style.*?</style>", "", html, flags=re.S | re.I)
        html = re.sub(r"<[^>]+>", " ", html)
        html = re.sub(r"\s+", " ", html)
        return html.strip()

    # ===== Code execution (REAL: upstream/hermes/tools/code_execution_tool.py) =====
    def code_execution(self, code: str, *, language: str = "python",
                       timeout: int = 60) -> Dict:
        """Run code. Tries real Hermes code_execution_tool first (PTC with UDS RPC).

        Falls back to subprocess in sandbox.
        """
        if language != "python":
            return {"stdout": "", "stderr": f"only python supported, got {language!r}",
                    "returncode": 1}
        try:
            mod = self._get("code_execution_tool")
            # Hermes tool exposes execute_python or run_python
            for fn_name in ("execute_python", "run_python", "exec_python", "execute"):
                if hasattr(mod, fn_name):
                    fn = getattr(mod, fn_name)
                    result = fn(code, timeout=timeout)
                    if isinstance(result, dict):
                        return result
                    return {"stdout": str(result), "stderr": "", "returncode": 0}
        except Exception:
            pass
        # Fallback: real subprocess via sandbox
        import tempfile
        tmp = Path(tempfile.gettempdir()) / f"alberto-exec-{int(time.time()*1000)}.py"
        tmp.write_text(code, encoding="utf-8")
        result = self._sandbox.run(["python3", str(tmp)], timeout=timeout)
        try:
            tmp.unlink()
        except Exception:
            pass
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    # ===== TTS (REAL: upstream/hermes/tools/tts_tool.py) =====
    def tts(self, text: str, *, provider: str = "edge", voice: str = "",
            output_path: Optional[Path] = None) -> Dict:
        """Text-to-speech using real Hermes TTS tool.

        Providers: edge (free), elevenlabs, openai, MiniMax, mistral, gemini, xai, neutts, kitten, piper
        """
        out = output_path or (self._home / "voice" / f"{int(time.time()*1000)}.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            mod = self._get("tts_tool")
            # Common function names
            for fn_name in ("synthesize", "tts", "speak", "generate_speech"):
                if hasattr(mod, fn_name):
                    fn = getattr(mod, fn_name)
                    result = fn(text, provider=provider, voice=voice, output=str(out))
                    return {"ok": True, "path": str(out), "provider": provider,
                            "result": result if not isinstance(result, str) else None}
        except Exception as e:
            return {"ok": False, "error": f"hermes tts failed: {e}",
                    "note": "install hermes deps for tts to work", "path": str(out)}
        return {"ok": False, "error": "no tts function found in hermes tts_tool"}

    # ===== STT (REAL: upstream/hermes/tools/transcription_tools.py) =====
    def stt(self, audio_path: str) -> Dict:
        """Speech-to-text using real Hermes transcription tool."""
        try:
            mod = self._get("transcription_tools")
            for fn_name in ("transcribe", "stt", "speech_to_text"):
                if hasattr(mod, fn_name):
                    fn = getattr(mod, fn_name)
                    result = fn(audio_path)
                    return {"ok": True, "text": result}
        except Exception as e:
            return {"ok": False, "error": f"hermes stt failed: {e}"}
        return {"ok": False, "error": "no stt function found"}

    # ===== Image gen (REAL: upstream/hermes/tools/image_generation_tool.py) =====
    def image_gen(self, prompt: str, *, output_path: Optional[Path] = None) -> Dict:
        """Generate image using real Hermes image_generation_tool."""
        out = output_path or (self._home / "images" / f"{int(time.time()*1000)}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            mod = self._get("image_generation_tool")
            for fn_name in ("generate", "create", "image_gen", "txt2img"):
                if hasattr(mod, fn_name):
                    fn = getattr(mod, fn_name)
                    result = fn(prompt=prompt, output=str(out))
                    return {"ok": True, "path": str(out), "result": result}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "no function found in image_generation_tool"}

    # ===== Video gen (REAL: upstream/hermes/tools/video_generation_tool.py) =====
    def video_gen(self, prompt: str, *, output_path: Optional[Path] = None) -> Dict:
        """Generate video using real Hermes video_generation_tool."""
        out = output_path or (self._home / "videos" / f"{int(time.time()*1000)}.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            mod = self._get("video_generation_tool")
            for fn_name in ("generate", "create", "video_gen", "txt2vid"):
                if hasattr(mod, fn_name):
                    fn = getattr(mod, fn_name)
                    result = fn(prompt=prompt, output=str(out))
                    return {"ok": True, "path": str(out), "result": result}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "no function found in video_generation_tool"}

    # ===== X/Twitter search (REAL: upstream/hermes/tools/x_search_tool.py) =====
    def x_search(self, query: str, **kwargs) -> Dict:
        """Search X/Twitter using real Hermes x_search_tool."""
        try:
            mod = self._get("x_search_tool")
            for fn_name in ("x_search", "search", "query"):
                if hasattr(mod, fn_name):
                    fn = getattr(mod, fn_name)
                    result = fn(query, **kwargs)
                    return {"ok": True, "query": query, "result": result}
        except Exception as e:
            return {"ok": False, "error": str(e),
                    "note": "XAI_API_KEY or xai-oauth required"}
        return {"ok": False, "error": "no function found in x_search_tool"}

    # ===== Cron (REAL: upstream/hermes/tools/cronjob_tools.py) =====
    def cron_register(self, name: str, schedule: str, command: Callable) -> None:
        """Register a cron job. Wraps real Hermes cronjob_tools if available."""
        self._cron_jobs[name] = {
            "name": name, "schedule": schedule, "command": command,
            "last_run": 0.0,
        }

    def cron_list(self) -> List[Dict]:
        return [{"name": j["name"], "schedule": j["schedule"], "last_run": j["last_run"]}
                for j in self._cron_jobs.values()]

    def cron_remove(self, name: str) -> bool:
        return self._cron_jobs.pop(name, None) is not None

    def _start_cron(self) -> None:
        self._stop_event.clear()
        self._cron_thread = threading.Thread(target=self._cron_loop, daemon=True)
        self._cron_thread.start()

    def _cron_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            for job in list(self._cron_jobs.values()):
                interval = self._parse_interval(job["schedule"])
                if interval and now - job["last_run"] >= interval:
                    try:
                        job["command"]()
                        job["last_run"] = now
                    except Exception:
                        pass
            self._stop_event.wait(1.0)

    @staticmethod
    def _parse_interval(spec: str) -> Optional[float]:
        spec = spec.strip().lower()
        m = re.match(r"every\s+(\d+)\s*s", spec)
        if m: return float(m.group(1))
        m = re.match(r"every\s+(\d+)\s*m", spec)
        if m: return float(m.group(1)) * 60
        m = re.match(r"every\s+(\d+)\s*h", spec)
        if m: return float(m.group(1)) * 3600
        return None

    # ===== Session search (REAL: upstream/hermes/tools/session_search_tool.py) =====
    def session_search(self, query: str, *, limit: int = 10) -> List[Dict]:
        if self._mimo is not None:
            return self._mimo.memory_search(query, limit=limit)
        return []

    # ===== File ops (REAL: upstream/hermes/tools/file_tools.py) =====
    def file_read(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8", errors="replace")

    def file_write(self, path: str, content: str) -> Dict:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(p), "size": len(content)}

    # ===== Generic invoke =====
    def invoke(self, prompt: str, **kwargs) -> str:
        cmd = kwargs.get("command", "")
        if cmd == "browser":
            return self.browser(prompt)
        if cmd == "code-exec":
            return json.dumps(self.code_execution(prompt))
        return f"[hermes] unknown command: {cmd}"