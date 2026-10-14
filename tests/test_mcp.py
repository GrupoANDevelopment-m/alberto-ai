"""Regression tests for MCP stdio protocol lifecycle and tool validation."""
import json
import sys
from pathlib import Path

from alberto.runtime.mcp import MCPClient


_FAKE_SERVER = r"""
import json
import sys
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method = msg.get("method")
    if method == "initialize":
        print(json.dumps({
            "jsonrpc": "2.0", "id": msg["id"],
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "1.0"},
            },
        }), flush=True)
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        print(json.dumps({
            "jsonrpc": "2.0", "id": msg["id"],
            "result": {"tools": [{
                "name": "echo", "description": "test echo",
                "inputSchema": {"type": "object"},
            }]},
        }), flush=True)
    elif method == "tools/call":
        print(json.dumps({
            "jsonrpc": "2.0", "id": msg["id"],
            "result": {"content": [{"type": "text", "text": json.dumps(msg["params"]["arguments"])}]},
        }), flush=True)
"""


def _client(tmp_path: Path) -> MCPClient:
    client = MCPClient(config_path=tmp_path / "mcp.json")
    client.add(
        "fake",
        command=sys.executable,
        args=["-u", "-c", _FAKE_SERVER],
    )
    return client


def test_connect_performs_initialize_and_tools_list(tmp_path):
    client = _client(tmp_path)
    try:
        assert client.connect("fake") is True
        server = client.servers["fake"]
        assert server.tools == ["echo"]
        assert server.process is not None
    finally:
        client.disconnect("fake")


def test_call_uses_discovered_tool_and_returns_result(tmp_path):
    client = _client(tmp_path)
    result = client.call("fake", "echo", {"message": "hello"})
    assert result["ok"] is True
    assert result["tools_available"] == ["echo"]
    assert json.loads(result["result"]["content"][0]["text"]) == {"message": "hello"}


def test_call_rejects_tool_not_advertised_by_server(tmp_path):
    client = _client(tmp_path)
    result = client.call("fake", "not-a-tool", {})
    assert result["ok"] is False
    assert "not advertised" in result["error"]
    assert result["tools_available"] == ["echo"]


def test_call_rejects_non_object_arguments(tmp_path):
    client = _client(tmp_path)
    result = client.call("fake", "echo", ["not", "an", "object"])
    assert result["ok"] is False
    assert "must be an object" in result["error"]
