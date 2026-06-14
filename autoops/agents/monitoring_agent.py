"""Monitoring agent node backed by the Monitoring MCP server."""

import json
import re
from pathlib import Path

from autoops.mcp_client import call_mcp_tool
from autoops.state import AutoOpsState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MONITORING_MCP_SERVER = PROJECT_ROOT / "autoops" / "mcp" / "mcp_monitoring.py"


def _select_tool_and_args(task: str) -> tuple[str, dict]:
    """Map a monitoring task to an MCP tool and arguments."""
    normalized = task.lower()
    service_name = _extract_service_name(task)

    if "deployment" in normalized or "deploy" in normalized or "history" in normalized:
        return "get_deployment_history", {"service_name": service_name}
    if "incident" in normalized or "summary" in normalized:
        return "get_incident_summary", {"service_name": service_name}
    return "get_service_health", {"service_name": service_name}


def _extract_service_name(task: str) -> str:
    """Extract a service-like name from a natural-language task."""
    match = re.search(r"\b([\w-]+-service)\b", task)
    if match:
        return match.group(1)
    return "checkout-service"


async def _call_monitoring_tool(tool_name: str, args: dict | None = None) -> str:
    """Call a Monitoring MCP tool over stdio and return text content."""
    return await call_mcp_tool(
        server_path=MONITORING_MCP_SERVER,
        tool_name=tool_name,
        args=args,
        agent="monitoring",
        url_env_var="MONITORING_MCP_URL",
        default_sse_url="http://localhost:8004/sse",
        project_root=PROJECT_ROOT,
    )


async def monitoring_node(state: AutoOpsState) -> AutoOpsState:
    """Handle monitoring tasks using MCP tools."""
    task = state["current_task"]
    tool_name, args = _select_tool_and_args(task)
    output = await _call_monitoring_tool(tool_name, args)

    return {
        "agent_outputs": {
            **state["agent_outputs"],
            "monitoring": output,
        }
    }
