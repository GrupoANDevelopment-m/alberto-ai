"""
Alberto AI — HTTP server.

Routes:
  GET  /                       → frontend/index.html
  GET  /css/*, /js/*, /assets/* → static
  GET  /api/status             → engine status
  GET  /api/banner             → identity banner
  POST /api/chat               → streaming chat (SSE)
  GET  /api/strategy           → orchestrator decision
  GET  /api/memory/list        → all memory keys
  GET  /api/memory/get         → get by key
  GET  /api/memory/search      → search by query
  POST /api/memory/set         → set key/value
  DELETE /api/memory/delete    → delete by key
  GET  /api/squad/list
  GET  /api/squad/describe
  POST /api/squad/activate
  POST /api/squad/hibernate
  POST /api/squad/run
  GET  /api/shortcut/list
  POST /api/shortcut/add
  DELETE /api/shortcut/remove
  POST /api/shortcut/use
  GET  /api/tools/list
  POST /api/tools/invoke
  GET  /api/model/list
  POST /api/model/set
  GET  /api/model/test
  POST /api/hermes/browser
  POST /api/hermes/exec
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from alberto.agent import Alberto
from alberto.identity import get_banner as banner_text, NAME, VERSION
from alberto.engines.base import EngineInfo
from alberto.model_router import ModelSpec
from alberto.tools_registry import list_tools, invoke_tool


# ===== Pydantic models =====
class ChatRequest(BaseModel):
    prompt: str
    squad: Optional[str] = None
    conversation_id: Optional[str] = None

class MemorySetRequest(BaseModel):
    key: str
    value: str
    tags: Optional[str] = None

class SquadActivateRequest(BaseModel):
    name: str

class SquadRunRequest(BaseModel):
    name: str
    prompt: str

class ShortcutAddRequest(BaseModel):
    key: str
    expansion: str

class ShortcutUseRequest(BaseModel):
    key: str
    args: str = ""

class ModelSetRequest(BaseModel):
    task: str
    provider: str
    model_id: str
    base_url: str
    credential_env: str

class ToolInvokeRequest(BaseModel):
    name: str
    args: dict = {}

class HermesBrowserRequest(BaseModel):
    url: str

class HermesExecRequest(BaseModel):
    code: str
    language: str = "python"


# ===== App factory =====
def create_app(alberto: Optional[Alberto] = None,
               frontend_dir: Optional[Path] = None) -> FastAPI:
    if alberto is None:
        base = Path(__file__).parent.parent.parent
        alberto = Alberto(
            catalog_dir=base / "workflows",
            personas_dir=base / "personas",
        )

    if frontend_dir is None:
        frontend_dir = Path(__file__).parent.parent.parent / "frontend"
    frontend_dir = Path(frontend_dir)  # ensure Path

    app = FastAPI(title=NAME, version=VERSION, docs_url="/__docs")
    app.state.alberto = alberto

    # ===== Frontend =====
    @app.get("/", response_class=FileResponse)
    async def index():
        return FileResponse(frontend_dir / "index.html")

    # Static mounts
    for sub in ("css", "js", "assets"):
        d = frontend_dir / sub
        if d.exists():
            app.mount(f"/{sub}", StaticFiles(directory=str(d)), name=sub)

    # ===== Identity =====
    @app.get("/api/banner")
    async def banner():
        return {"text": banner_text()}

    @app.get("/api/status")
    async def status():
        a = app.state.alberto
        return a.status()

    # ===== Strategy =====
    @app.get("/api/strategy")
    async def strategy(prompt: str):
        a = app.state.alberto
        strat = a.orchestrator.decide(prompt, active_squad=a.catalog.active_squad)
        return {
            "mode": strat.mode, "reason": strat.reason,
            "engine": strat.engine, "squad": strat.squad,
            "task_routing": strat.task_routing,
        }

    # ===== Chat (natural conversation, streaming SSE) =====
    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        """Natural conversation with Alberto. Returns SSE events.

        Events:
          - {type: 'text', content: '...'}  - response chunk
          - {type: 'done', strategy, tool_calls, conversation_id}  - end
          - {type: 'error', error: '...'}  - on error
        """
        a = app.state.alberto

        async def gen():
            try:
                result = a.chat(req.prompt, conversation_id=req.conversation_id)
                text = result.get("response", "")
                for chunk in chunk_text(text, size=20):
                    yield "data: " + json.dumps({"type": "text", "content": chunk}) + "\n\n"
                    await asyncio.sleep(0)
                yield "data: " + json.dumps({
                    "type": "done",
                    "strategy": result.get("strategy"),
                    "tool_calls": result.get("tool_calls", []),
                    "conversation_id": result.get("conversation_id"),
                }) + "\n\n"
            except Exception as e:
                yield "data: " + json.dumps({"type": "error", "error": str(e)}) + "\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    # ===== Memory =====
    @app.get("/api/memory/list")
    async def memory_list():
        return app.state.alberto.memory_list()

    @app.get("/api/memory/get")
    async def memory_get(key: str):
        v = app.state.alberto.memory_get(key)
        if v is None:
            raise HTTPException(404, f"key not found: {key}")
        return {"key": key, "value": v}

    @app.get("/api/memory/search")
    async def memory_search(q: str, limit: int = 10):
        return app.state.alberto.memory_search(q, limit=limit)

    @app.post("/api/memory/set")
    async def memory_set(req: MemorySetRequest):
        app.state.alberto.memory_set(req.key, req.value, tags=req.tags)
        return {"ok": True, "key": req.key}

    @app.delete("/api/memory/delete")
    async def memory_delete(key: str):
        a = app.state.alberto
        try:
            a._sandbox_run_unsafe(f"DELETE FROM memory WHERE key=?", (key,))
            return {"ok": True}
        except Exception as e:
            raise HTTPException(500, str(e))

    # ===== Squads =====
    @app.get("/api/squad/list")
    async def squad_list():
        return app.state.alberto.squad_list()

    @app.get("/api/squad/describe")
    async def squad_describe(name: str):
        d = app.state.alberto.squad_describe(name)
        if d is None:
            raise HTTPException(404, "squad not found")
        return d

    @app.post("/api/squad/activate")
    async def squad_activate(req: SquadActivateRequest):
        try:
            app.state.alberto.squad_activate(req.name)
            return {"ok": True, "active": req.name}
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/squad/hibernate")
    async def squad_hibernate():
        app.state.alberto.squad_hibernate()
        return {"ok": True}

    @app.post("/api/squad/run")
    async def squad_run(req: SquadRunRequest):
        return app.state.alberto.run_squad(req.name, req.prompt)

    # ===== Shortcuts =====
    @app.get("/api/shortcut/list")
    async def shortcut_list():
        out = {}
        for k, v in app.state.alberto.shortcuts.list().items():
            out[k] = {"expansion": v.expansion, "use_count": v.use_count,
                      "created_at": v.created_at}
        return out

    @app.post("/api/shortcut/add")
    async def shortcut_add(req: ShortcutAddRequest):
        sc = app.state.alberto.shortcuts.add(req.key, req.expansion)
        return {"ok": True, "key": req.key, "expansion": sc.expansion}

    @app.delete("/api/shortcut/remove")
    async def shortcut_remove(key: str):
        ok = app.state.alberto.shortcuts.remove(key)
        return {"ok": ok}

    @app.post("/api/shortcut/use")
    async def shortcut_use(req: ShortcutUseRequest):
        out = app.state.alberto.shortcuts.expand(req.key, req.args)
        if out is None:
            raise HTTPException(404, "shortcut not found")
        return {"expansion": out}

    # ===== Tools =====
    @app.get("/api/tools/list")
    async def tools_list():
        return list_tools()

    @app.post("/api/tools/invoke")
    async def tools_invoke(req: ToolInvokeRequest):
        return invoke_tool(app.state.alberto, req.name, req.args)

    # ===== Models =====
    @app.get("/api/model/list")
    async def model_list():
        out = []
        for t in app.state.alberto.model_list():
            spec = app.state.alberto.router.resolve(t)
            out.append({"task": t, "provider": spec.provider,
                        "model_id": spec.model_id, "base_url": spec.base_url})
        return out

    @app.post("/api/model/set")
    async def model_set(req: ModelSetRequest):
        app.state.alberto.model_set(
            req.task, provider=req.provider, model_id=req.model_id,
            base_url=req.base_url, credential_env=req.credential_env,
        )
        return {"ok": True}

    @app.get("/api/model/test")
    async def model_test(task: str):
        env = app.state.alberto.model_test(task)
        if not env:
            raise HTTPException(404, f"no model configured for task {task!r}")
        return env

    # ===== Hermes =====
    @app.post("/api/hermes/browser")
    async def hermes_browser(req: HermesBrowserRequest):
        a = app.state.alberto
        if not a.hermes.is_running():
            a.hermes.start()
        return {"text": a.hermes.browser(req.url)}

    @app.post("/api/hermes/exec")
    async def hermes_exec(req: HermesExecRequest):
        a = app.state.alberto
        return a.hermes.code_execution(req.code, language=req.language)

    @app.exception_handler(Exception)
    async def all_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "type": type(exc).__name__},
        )

    return app


def chunk_text(text: str, size: int = 24):
    """Yield text in small chunks for SSE streaming."""
    for i in range(0, len(text), size):
        yield text[i:i + size]


def run_server(host: str = "127.0.0.1", port: int = 8741, **kwargs):
    import uvicorn
    app = create_app(**kwargs)
    uvicorn.run(app, host=host, port=port, log_level="warning")