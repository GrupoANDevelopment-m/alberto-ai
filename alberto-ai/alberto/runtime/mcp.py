"""MCP (Model Context Protocol) client — connects to MCP servers.

Supports:
- stdio transport (subprocess)
- HTTP/SSE transport (network)

Discovery:
- `mcp://` URIs in skills or shortcuts
- MCP config file: ~/.config/alberto/mcp.json
- Auto-discover: scan skills/optional/mcp/*/mcp.json

Usage:
  alberto mcp add <name> <command> [args...]
  alberto mcp connect <name>
  alberto mcp list
  alberto mcp call <name> <tool> [args]
"""
from __future__ import annotations
import json
import os
import select
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MCPServer:
    name: str
    transport: str = "stdio"  # "stdio" | "http" | "sse"
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    # Runtime
    process: Optional[subprocess.Popen] = None
    tools: List[str] = field(default_factory=list)


class MCPClient:
    """Manages connections to MCP servers (stdio only for now)."""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path.home() / ".config" / "alberto" / "mcp.json"
        self.config_path = config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.servers: Dict[str, MCPServer] = {}
        self._load_config()
        self._auto_discover()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            self.config_path.write_text("{}")
            return
        try:
            data = json.loads(self.config_path.read_text())
            for name, cfg in data.items():
                self.servers[name] = MCPServer(
                    name=name,
                    transport=cfg.get("transport", "stdio"),
                    command=cfg.get("command"),
                    args=cfg.get("args", []),
                    env=cfg.get("env", {}),
                    url=cfg.get("url"),
                )
        except Exception as e:
            print(f"[mcp] config load error: {e}", file=sys.stderr)

    def _save_config(self) -> None:
        data = {}
        for name, srv in self.servers.items():
            data[name] = {
                "transport": srv.transport,
                "command": srv.command,
                "args": srv.args,
                "env": srv.env,
                "url": srv.url,
            }
        self.config_path.write_text(json.dumps(data, indent=2))

    def _auto_discover(self) -> None:
        """Scan skills/optional/mcp/*/mcp.json and add servers."""
        skills_dir = Path(__file__).parent.parent.parent / "skills" / "optional" / "mcp"
        if not skills_dir.exists():
            return
        for d in skills_dir.iterdir():
            cfg = d / "mcp.json"
            if cfg.exists():
                try:
                    data = json.loads(cfg.read_text())
                    for name, srv_cfg in data.items():
                        if name not in self.servers:
                            self.servers[name] = MCPServer(
                                name=name,
                                transport=srv_cfg.get("transport", "stdio"),
                                command=srv_cfg.get("command"),
                                args=srv_cfg.get("args", []),
                                env=srv_cfg.get("env", {}),
                                url=srv_cfg.get("url"),
                            )
                except Exception:
                    pass

    def add(self, name: str, *, command: str, args: Optional[List[str]] = None,
            env: Optional[Dict[str, str]] = None, url: Optional[str] = None,
            transport: str = "stdio") -> None:
        self.servers[name] = MCPServer(
            name=name, transport=transport, command=command,
            args=args or [], env=env or {}, url=url,
        )
        self._save_config()

    def remove(self, name: str) -> bool:
        if name in self.servers:
            del self.servers[name]
            self._save_config()
            return True
        return False

    def list_servers(self) -> List[Dict[str, Any]]:
        return [
            {"name": s.name, "transport": s.transport, "command": s.command,
             "url": s.url, "tools": s.tools, "connected": s.process is not None}
            for s in self.servers.values()
        ]

    def connect(self, name: str) -> bool:
        """Spawn stdio server and do MCP handshake."""
        srv = self.servers.get(name)
        if not srv:
            return False
        if srv.transport != "stdio":
            print(f"[mcp] {name}: only stdio transport implemented yet")
            return False
        if srv.process is not None:
            return True  # already connected
        try:
            env = {**os.environ, **srv.env}
            srv.process = subprocess.Popen(
                [srv.command] + srv.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env,
            )
            # Send initialize request (simplified)
            init_req = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05",
                           "capabilities": {},
                           "clientInfo": {"name": "alberto-ai", "version": "0.1.0"}}
            }
            srv.process.stdin.write((json.dumps(init_req) + "\n").encode())
            srv.process.stdin.flush()
            # Read response (non-blocking would be better, but sync is fine for connect)
            import select
            ready, _, _ = select.select([srv.process.stdout], [], [], 2.0)
            if ready:
                line = srv.process.stdout.readline()
                resp = json.loads(line.decode())
                srv.tools = [t.get("name") for t in resp.get("result", {}).get("tools", [])]
            return True
        except Exception as e:
            print(f"[mcp] connect {name} failed: {e}", file=sys.stderr)
            srv.process = None
            return False

    def disconnect(self, name: str) -> bool:
        srv = self.servers.get(name)
        if not srv or not srv.process:
            return False
        srv.process.terminate()
        srv.process.wait(timeout=5)
        srv.process = None
        return True

    def call(self, name: str, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on an MCP server. Auto-connects in a long-lived daemon."""
        srv = self.servers.get(name)
        if not srv:
            return {"ok": False, "error": f"server {name} not configured"}
        # Auto-connect: spawn a fresh process for this call (no daemon state)
        # We spawn, initialize, call, disconnect — simpler and works across subprocesses
        if srv.transport != "stdio":
            return {"ok": False, "error": f"transport {srv.transport} not implemented"}
        try:
            env = {**os.environ, **srv.env}
            proc = subprocess.Popen(
                [srv.command] + srv.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env,
            )
            # Initialize
            init_req = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05",
                           "capabilities": {},
                           "clientInfo": {"name": "alberto-ai", "version": "0.1.0"}}
            }
            proc.stdin.write((json.dumps(init_req) + "\n").encode())
            proc.stdin.flush()
            ready, _, _ = select.select([proc.stdout], [], [], 5.0)
            if ready:
                line = proc.stdout.readline()
                resp = json.loads(line.decode())
                srv.tools = [t.get("name") for t in resp.get("result", {}).get("tools", [])]
            # Call tool
            req = {
                "jsonrpc": "2.0", "id": int(time.time() * 1000),
                "method": "tools/call",
                "params": {"name": tool, "arguments": args}
            }
            proc.stdin.write((json.dumps(req) + "\n").encode())
            proc.stdin.flush()
            ready, _, _ = select.select([proc.stdout], [], [], 30.0)
            if ready:
                line = proc.stdout.readline()
                result = json.loads(line.decode())
                proc.terminate()
                try: proc.wait(timeout=2)
                except: proc.kill()
                return {"ok": True, "result": result, "tools_available": srv.tools}
            proc.terminate()
            try: proc.wait(timeout=2)
            except: proc.kill()
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="alberto mcp")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="add MCP server")
    p_add.add_argument("name")
    p_add.add_argument("command")
    p_add.add_argument("args", nargs="*")
    p_con = sub.add_parser("connect")
    p_con.add_argument("name")
    p_dc = sub.add_parser("disconnect")
    p_dc.add_argument("name")
    sub.add_parser("list")
    p_call = sub.add_parser("call")
    p_call.add_argument("name")
    p_call.add_argument("tool")
    p_call.add_argument("args_json", nargs="?", default="{}")
    args = p.parse_args(argv)
    c = MCPClient()
    if args.cmd == "add":
        c.add(args.name, command=args.command, args=args.args)
        print(f"added {args.name}")
    elif args.cmd == "connect":
        ok = c.connect(args.name)
        print(f"{'connected' if ok else 'failed'}: {args.name}")
    elif args.cmd == "disconnect":
        c.disconnect(args.name)
    elif args.cmd == "list":
        for s in c.list_servers():
            print(f"  {s['name']:20s} {s['transport']:6s} {s['command'] or s['url']} tools={s['tools']}")
    elif args.cmd == "call":
        result = c.call(args.name, args.tool, json.loads(args.args_json))
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
