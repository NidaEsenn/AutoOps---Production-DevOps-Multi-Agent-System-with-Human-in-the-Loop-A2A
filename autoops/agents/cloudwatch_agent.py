"""CloudWatch agent node backed by the CloudWatch MCP server."""

import json
import re
from pathlib import Path

from autoops.mcp_client import call_mcp_tool
from autoops.state import AutoOpsState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLOUDWATCH_MCP_SERVER = PROJECT_ROOT / "autoops" / "mcp" / "mcp_cloudwatch.py"


def _select_tool_and_args(task: str) -> tuple[str, dict]:
    """Map a CloudWatch task to an MCP tool and arguments."""
    normalized = task.lower()
    service_name = _extract_service_name(task)

    if "deployment" in normalized or "deploy" in normalized:
        return "describe_recent_deployments", {"service_name": service_name}
    if "alarm" in normalized:
        return "list_alarms", {"state_filter": "ALARM"}
    if "log" in normalized:
        return "get_log_events", {"log_group": _extract_log_group(task, service_name)}
    if "latency" in normalized:
        return "get_metrics", _metric_args("AutoOps/Services", "Latency", service_name)
    return "get_metrics", _metric_args("AutoOps/Services", "ErrorRate", service_name)


def _extract_service_name(task: str) -> str:
    """Extract a service-like name from a natural-language task."""
    match = re.search(r"\b([\w-]+-service)\b", task)
    if match:
        return match.group(1)
    return "checkout-service"


def _extract_log_group(task: str, service_name: str) -> str:
    """Extract an explicit log group, otherwise infer one from service name."""
    match = re.search(r"(/\S+)", task)
    if match:
        return match.group(1)
    return f"/aws/autoops/{service_name}"


def _metric_args(namespace: str, metric_name: str, service_name: str) -> dict:
    """Build default CloudWatch metric arguments for service metrics."""
    return {
        "namespace": namespace,
        "metric_name": metric_name,
        "dimensions": {"ServiceName": service_name},
        "minutes": 60,
    }


async def _call_cloudwatch_tool(tool_name: str, args: dict | None = None) -> str:
    """Call a CloudWatch MCP tool over stdio and return text content."""
    return await call_mcp_tool(
        server_path=CLOUDWATCH_MCP_SERVER,
        tool_name=tool_name,
        args=args,
        agent="cloudwatch",
        url_env_var="CLOUDWATCH_MCP_URL",
        default_sse_url="http://localhost:8002/sse",
        project_root=PROJECT_ROOT,
    )


async def cloudwatch_node(state: AutoOpsState) -> AutoOpsState:
    """Handle CloudWatch tasks using MCP tools."""
    task = state["current_task"]
    tool_name, args = _select_tool_and_args(task)
    output = await _call_cloudwatch_tool(tool_name, args)

    return {
        "agent_outputs": {
            **state["agent_outputs"],
            "cloudwatch": output,
        }
    }
