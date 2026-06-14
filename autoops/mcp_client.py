"""Shared MCP client helpers for AutoOps agents."""

import importlib.util
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

from autoops.observability import tool_span


async def call_mcp_tool(
    *,
    server_path: Path,
    tool_name: str,
    args: dict | None,
    agent: str,
    url_env_var: str,
    default_sse_url: str,
    project_root: Path,
) -> str:
    """Call an MCP tool.

    Transport (MCP_TRANSPORT env):
    - "inmemory" (default): run the FastMCP server in-process — no per-call
      subprocess spawn, so latency is dominated by the tool's own work.
    - "stdio": spawn the server as a subprocess (process isolation).
    - "sse": connect to a remote server over SSE (Docker/cloud gateway).
    """
    transport = os.getenv("MCP_TRANSPORT", "inmemory").lower()
    with tool_span(tool_name, agent=agent, server=str(server_path), transport=transport):
        if transport == "sse":
            return await _call_sse_tool(
                url=os.getenv(url_env_var, default_sse_url),
                tool_name=tool_name,
                args=args,
            )
        if transport == "stdio":
            return await _call_stdio_tool(
                server_path=server_path,
                tool_name=tool_name,
                args=args,
                project_root=project_root,
            )
        return await _call_inmemory_tool(server_path=server_path, tool_name=tool_name, args=args)


async def _call_stdio_tool(server_path: Path, tool_name: str, args: dict | None, project_root: Path) -> str:
    """Call an MCP server over stdio."""
    server_params = StdioServerParameters(
        command=sys.executable or "python3",
        args=[str(server_path)],
        env=os.environ.copy(),
        cwd=project_root,
    )

    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(server_params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args or {})

    return _text_result(result)


@lru_cache(maxsize=None)
def _load_server_object(server_path_str: str):
    """Import an MCP server module by file path and return its FastMCP object.

    Cached so the module (and its imports) is loaded once per process, which is
    what makes the in-memory transport fast on repeated calls.
    """
    module_name = f"_autoops_mcp_srv_{Path(server_path_str).stem}"
    spec = importlib.util.spec_from_file_location(module_name, server_path_str)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mcp


async def _call_inmemory_tool(server_path: Path, tool_name: str, args: dict | None) -> str:
    """Call an MCP tool in-process via FastMCP's in-memory transport (no subprocess)."""
    from fastmcp import Client

    server = _load_server_object(str(server_path))
    async with Client(server) as client:
        result = await client.call_tool(tool_name, args or {})

    parts = [
        content.text
        for content in (getattr(result, "content", None) or [])
        if getattr(content, "text", None)
    ]
    if parts:
        return "\n".join(parts)
    data = getattr(result, "data", None)
    return json.dumps(data, indent=2, default=str) if data is not None else ""


async def _call_sse_tool(url: str, tool_name: str, args: dict | None) -> str:
    """Call an MCP server over SSE."""
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args or {})

    return _text_result(result)


def _text_result(result) -> str:
    """Return text content from an MCP tool result."""
    text_parts = [content.text for content in result.content if content.type == "text"]
    if text_parts:
        return "\n".join(text_parts)
    return json.dumps(result.model_dump(), indent=2)
