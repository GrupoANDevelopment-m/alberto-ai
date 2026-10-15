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


def test_server_process_does_not_inherit_unrelated_environment_secrets(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.servers["fake"].env = {"MCP_EXPLICIT_SETTING": "allowed"}
    monkeypatch.setenv("ALBERTO_PRIVATE_TEST_TOKEN", "must-not-leak")
    captured = {}

    class FakeProcess:
        stdin = None
        stdout = None
        stderr = None

        def poll(self):
            return 0

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr("alberto.runtime.mcp.subprocess.Popen", fake_popen)
    monkeypatch.setattr(MCPClient, "_initialize_process", lambda cls, proc: ["echo"])
    assert client.connect("fake") is True
    assert "ALBERTO_PRIVATE_TEST_TOKEN" not in captured["env"]
    assert captured["env"]["MCP_EXPLICIT_SETTING"] == "allowed"
    assert "PATH" in captured["env"]
    client.disconnect("fake")


def test_server_env_rejects_invalid_values():
    import pytest

    with pytest.raises(ValueError, match="invalid key"):
        MCPClient._build_server_env({"BAD": "value" + chr(0)})
    with pytest.raises(ValueError, match="invalid key"):
        MCPClient._build_server_env({"BAD-NAME": "value"})



def test_load_config_skips_malformed_entries_and_keeps_valid_servers(tmp_path, capsys):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({
        "bad-null": None,
        "bad-args": {
            "transport": "stdio", "command": sys.executable,
            "args": ["-c", 3],
        },
        "good": {
            "transport": "stdio", "command": sys.executable,
            "args": ["-c", "print('ok')"], "env": {},
        },
    }))
    client = MCPClient(config_path=config)
    assert "good" in client.servers
    assert "bad-null" not in client.servers
    assert "bad-args" not in client.servers
    assert "ignoring invalid server config" in capsys.readouterr().err


def test_load_config_rejects_non_object_root(tmp_path, capsys):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps([{"name": "not-a-map"}]))
    client = MCPClient(config_path=config)
    assert client.servers == {}
    assert "root must be a JSON object" in capsys.readouterr().err


def test_add_rejects_invalid_server_config(tmp_path):
    import pytest
    client = MCPClient(config_path=tmp_path / "mcp.json")
    with pytest.raises(ValueError, match="invalid MCP server configuration"):
        client.add("bad", command=sys.executable, args=["-c", 42])
    with pytest.raises(ValueError, match="invalid MCP server configuration"):
        client.add("missing-command", transport="stdio")
    with pytest.raises(ValueError, match="invalid MCP server configuration"):
        client.add("unsupported", transport="grpc", command="server")


def test_http_and_sse_are_explicitly_unsupported_by_current_runtime(tmp_path):
    client = MCPClient(config_path=tmp_path / "mcp.json")
    client.servers["remote-http"] = __import__(
        "alberto.runtime.mcp", fromlist=["MCPServer"]
    ).MCPServer(name="remote-http", transport="http", url="https://example.invalid/mcp")
    result = client.call("remote-http", "echo", {})
    assert result["ok"] is False
    assert "not implemented" in result["error"]
