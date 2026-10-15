"""MCP client for stdio servers; HTTP/SSE are reserved but not implemented.

Implemented:
- stdio transport (subprocess, JSON-RPC initialize/tools/list/tools/call)

Not implemented (rejected explicitly at runtime):
- HTTP transport
- SSE transport

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
    """Manage MCP stdio servers. HTTP/SSE config entries are not executable yet."""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path.home() / ".config" / "alberto" / "mcp.json"
        self.config_path = config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.servers: Dict[str, MCPServer] = {}
        self._load_config()
        self._auto_discover()

    @staticmethod
    def _valid_server_config(name: Any, cfg: Any) -> bool:
        """Validate persisted MCP entries before they enter the runtime registry."""
        if not isinstance(name, str) or not name.strip() or name != name.strip() or not isinstance(cfg, dict):
            return False
        transport = cfg.get("transport", "stdio")
        if not isinstance(transport, str):
            return False
        command = cfg.get("command")
        args = cfg.get("args", [])
        env = cfg.get("env", {})
        url = cfg.get("url")
        if transport not in {"stdio", "http", "sse"}:
            return False
        if command is not None and (not isinstance(command, str) or not command.strip()):
            return False
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            return False
        if not isinstance(env, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in env.items()
        ):
            return False
        if url is not None and not isinstance(url, str):
            return False
        if transport == "stdio" and not command:
            return False
        if transport in {"http", "sse"} and not url:
            return False
        return True

    def _load_config(self) -> None:
        if not self.config_path.exists():
            self.config_path.write_text("{}")
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            print(f"[mcp] config load error: {e}", file=sys.stderr)
            return
        if not isinstance(data, dict):
            print("[mcp] config load error: root must be a JSON object", file=sys.stderr)
            return
        for name, cfg in data.items():
            if not self._valid_server_config(name, cfg):
                print(f"[mcp] ignoring invalid server config: {str(name)[:100]}", file=sys.stderr)
                continue
            self.servers[name] = MCPServer(
                name=name,
                transport=cfg.get("transport", "stdio"),
                command=cfg.get("command"),
                args=list(cfg.get("args", [])),
                env=dict(cfg.get("env", {})),
                url=cfg.get("url"),
            )

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
                    data = json.loads(cfg.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue
                    for name, srv_cfg in data.items():
                        if name not in self.servers and self._valid_server_config(name, srv_cfg):
                            self.servers[name] = MCPServer(
                                name=name,
                                transport=srv_cfg.get("transport", "stdio"),
                                command=srv_cfg.get("command"),
                                args=list(srv_cfg.get("args", [])),
                                env=dict(srv_cfg.get("env", {})),
                                url=srv_cfg.get("url"),
                            )
                except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                    continue

    def add(self, name: str, *, command: Optional[str] = None, args: Optional[List[str]] = None,
            env: Optional[Dict[str, str]] = None, url: Optional[str] = None,
            transport: str = "stdio") -> None:
        cfg = {
            "transport": transport, "command": command,
            "args": [] if args is None else args,
            "env": {} if env is None else env, "url": url,
        }
        if not self._valid_server_config(name, cfg):
            raise ValueError("invalid MCP server configuration")
        self.servers[name] = MCPServer(
            name=name, transport=transport, command=command,
            args=list(cfg["args"]), env=dict(cfg["env"]), url=url,
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

    @staticmethod
    def _read_response(proc: subprocess.Popen, expected_id: int, timeout: float) -> Dict[str, Any]:
        """Read JSON-RPC messages until the response matching expected_id arrives."""
        if proc.stdout is None:
            raise RuntimeError("MCP server stdout is unavailable")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed stdout before replying")
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("MCP server returned invalid JSON-RPC") from exc
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                continue
            if message.get("id") != expected_id:
                # Notifications and responses to other requests are not this response.
                continue
            if "error" in message:
                error = message["error"]
                raise RuntimeError(f"MCP JSON-RPC error: {error}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("MCP response has no valid result object")
            return result
        raise TimeoutError(f"timed out waiting for MCP response id={expected_id}")

    @classmethod
    def _initialize_process(cls, proc: subprocess.Popen, timeout: float = 5.0) -> List[str]:
        """Perform initialize → notifications/initialized → tools/list."""
        if proc.stdin is None:
            raise RuntimeError("MCP server stdin is unavailable")
        init_id = 1
        init_req = {
            "jsonrpc": "2.0", "id": init_id, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "alberto-ai", "version": "0.1.0"},
            },
        }
        proc.stdin.write((json.dumps(init_req) + "\n").encode("utf-8"))
        proc.stdin.flush()
        init_result = cls._read_response(proc, init_id, timeout)
        if not isinstance(init_result.get("protocolVersion"), str):
            raise RuntimeError("MCP initialize response missing protocolVersion")

        initialized = {
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }
        proc.stdin.write((json.dumps(initialized) + "\n").encode("utf-8"))
        proc.stdin.flush()

        list_id = 2
        proc.stdin.write((json.dumps({
            "jsonrpc": "2.0", "id": list_id, "method": "tools/list", "params": {},
        }) + "\n").encode("utf-8"))
        proc.stdin.flush()
        listing = cls._read_response(proc, list_id, timeout)
        tools = listing.get("tools")
        if not isinstance(tools, list):
            raise RuntimeError("MCP tools/list response missing tools array")
        names = []
        for item in tools:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.append(item["name"])
        return names

    @staticmethod
    def _stop_process(proc: Optional[subprocess.Popen]) -> None:
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    @staticmethod
    def _build_server_env(configured: Dict[str, str]) -> Dict[str, str]:
        """Pass a minimal process environment; secrets require explicit server config."""
        allowed = {
            "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL",
            "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC",
        }
        env = {key: value for key, value in os.environ.items() if key in allowed}
        if not isinstance(configured, dict):
            raise ValueError("MCP server env must be an object of string values")
        for key, value in configured.items():
            if (not isinstance(key, str) or not key
                    or not key.replace("_", "a").isalnum()
                    or key[0].isdigit()
                    or not isinstance(value, str)
                    or chr(0) in key or chr(0) in value):
                raise ValueError("MCP server env contains an invalid key or non-string value")
            env[key] = value
        return env

    def connect(self, name: str) -> bool:
        """Start an MCP stdio server and complete the protocol handshake."""
        srv = self.servers.get(name)
        if not srv or not srv.command or srv.transport != "stdio":
            return False
        if srv.process is not None and srv.process.poll() is None:
            return True
        proc = None
        try:
            env = self._build_server_env(srv.env)
            proc = subprocess.Popen(
                [srv.command] + srv.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env,
            )
            tools = self._initialize_process(proc)
            srv.process = proc
            srv.tools = tools
            return True
        except Exception as exc:
            print(f"[mcp] connect {name} failed: {exc}", file=sys.stderr)
            self._stop_process(proc)
            srv.process = None
            srv.tools = []
            return False

    def disconnect(self, name: str) -> bool:
        srv = self.servers.get(name)
        if not srv or not srv.process:
            return False
        proc = srv.process
        srv.process = None
        srv.tools = []
        self._stop_process(proc)
        return True

    def call(self, name: str, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Call a discovered tool over MCP stdio and always clean up the process."""
        srv = self.servers.get(name)
        if not srv:
            return {"ok": False, "error": f"server {name} not configured"}
        if srv.transport != "stdio":
            return {"ok": False, "error": f"transport {srv.transport} not implemented"}
        if not srv.command:
            return {"ok": False, "error": "server command is not configured"}
        if not isinstance(tool, str) or not tool:
            return {"ok": False, "error": "tool name must be a non-empty string"}
        if not isinstance(args, dict):
            return {"ok": False, "error": "tool arguments must be an object"}

        proc = None
        try:
            env = self._build_server_env(srv.env)
            proc = subprocess.Popen(
                [srv.command] + srv.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env,
            )
            available_tools = self._initialize_process(proc)
            srv.tools = available_tools
            if tool not in available_tools:
                return {"ok": False, "error": f"tool {tool!r} was not advertised by MCP server",
                        "tools_available": available_tools}
            if proc.stdin is None:
                raise RuntimeError("MCP server stdin is unavailable")
            request_id = 3
            request = {
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            }
            proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            proc.stdin.flush()
            result = self._read_response(proc, request_id, timeout=30.0)
            is_error = result.get("isError") is True
            return {"ok": not is_error, "result": result, "tools_available": available_tools}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:500]}
        finally:
            self._stop_process(proc)


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
