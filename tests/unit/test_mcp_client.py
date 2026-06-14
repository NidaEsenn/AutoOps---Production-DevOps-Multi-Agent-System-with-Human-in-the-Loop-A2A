from pathlib import Path

import pytest

from autoops import mcp_client


@pytest.mark.anyio
async def test_call_mcp_tool_uses_inmemory_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def fake_call_inmemory_tool(server_path: Path, tool_name: str, args: dict | None) -> str:
        calls.append((server_path, tool_name, args))
        return "ok"

    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.setattr(mcp_client, "_call_inmemory_tool", fake_call_inmemory_tool)

    result = await mcp_client.call_mcp_tool(
        server_path=Path("server.py"),
        tool_name="tool",
        args={"a": 1},
        agent="test",
        url_env_var="TEST_MCP_URL",
        default_sse_url="http://localhost:9999/sse",
        project_root=Path("."),
    )

    assert result == "ok"
    assert calls[0][1] == "tool"


@pytest.mark.anyio
async def test_call_mcp_tool_uses_stdio_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def fake_call_stdio_tool(server_path: Path, tool_name: str, args: dict | None, project_root: Path) -> str:
        calls.append((server_path, tool_name, args, project_root))
        return "ok"

    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setattr(mcp_client, "_call_stdio_tool", fake_call_stdio_tool)

    result = await mcp_client.call_mcp_tool(
        server_path=Path("server.py"),
        tool_name="tool",
        args={"a": 1},
        agent="test",
        url_env_var="TEST_MCP_URL",
        default_sse_url="http://localhost:9999/sse",
        project_root=Path("."),
    )

    assert result == "ok"
    assert calls[0][1] == "tool"


@pytest.mark.anyio
async def test_inmemory_tool_loads_server_and_calls_tool(tmp_path: Path) -> None:
    """The in-process transport loads a FastMCP server module and runs its tool."""
    server_file = tmp_path / "tmp_echo_server.py"
    server_file.write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('tmp-echo')\n"
        "@mcp.tool()\n"
        "async def echo(text: str) -> str:\n"
        "    return f'echo: {text}'\n"
    )

    result = await mcp_client._call_inmemory_tool(
        server_path=server_file, tool_name="echo", args={"text": "hi"}
    )

    assert result == "echo: hi"


@pytest.mark.anyio
async def test_call_mcp_tool_uses_sse_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def fake_call_sse_tool(url: str, tool_name: str, args: dict | None) -> str:
        calls.append((url, tool_name, args))
        return "ok"

    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    monkeypatch.setenv("TEST_MCP_URL", "http://mcp.example/sse")
    monkeypatch.setattr(mcp_client, "_call_sse_tool", fake_call_sse_tool)

    result = await mcp_client.call_mcp_tool(
        server_path=Path("server.py"),
        tool_name="tool",
        args={"a": 1},
        agent="test",
        url_env_var="TEST_MCP_URL",
        default_sse_url="http://localhost:9999/sse",
        project_root=Path("."),
    )

    assert result == "ok"
    assert calls == [("http://mcp.example/sse", "tool", {"a": 1})]
