"""Code Review agent node backed by the Code Review MCP server."""

import json
import re
from pathlib import Path

from autoops.mcp_client import call_mcp_tool
from autoops.state import AutoOpsState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODEREVIEW_MCP_SERVER = PROJECT_ROOT / "autoops" / "mcp" / "mcp_codereview.py"


def _select_tool_and_args(task: str) -> tuple[str, dict]:
    """Map a code review task to an MCP tool and arguments."""
    normalized = task.lower()

    if "diff" in normalized:
        return "get_diff_summary", {"diff_text": task}
    if "security" in normalized or "vulnerability" in normalized or "scan" in normalized or "sast" in normalized:
        return "run_security_scan", {"repo_path": _extract_path(task) or "."}
    return "run_linter", {"file_path": _extract_path(task) or "autoops/supervisor.py"}


def _extract_path(task: str) -> str | None:
    """Find a likely file or directory path in a natural-language task."""
    match = re.search(r"([\w./-]+\.py|[\w./-]+/[\w./-]*)", task)
    if match:
        return match.group(1)
    return None


async def _call_codereview_tool(tool_name: str, args: dict | None = None) -> str:
    """Call a Code Review MCP tool over stdio and return text content."""
    return await call_mcp_tool(
        server_path=CODEREVIEW_MCP_SERVER,
        tool_name=tool_name,
        args=args,
        agent="codereview",
        url_env_var="CODEREVIEW_MCP_URL",
        default_sse_url="http://localhost:8003/sse",
        project_root=PROJECT_ROOT,
    )


async def codereview_node(state: AutoOpsState) -> AutoOpsState:
    """Handle code review tasks using MCP tools."""
    task = state["current_task"]
    tool_name, args = _select_tool_and_args(task)
    output = await _call_codereview_tool(tool_name, args)

    return {
        "agent_outputs": {
            **state["agent_outputs"],
            "codereview": output,
        }
    }
