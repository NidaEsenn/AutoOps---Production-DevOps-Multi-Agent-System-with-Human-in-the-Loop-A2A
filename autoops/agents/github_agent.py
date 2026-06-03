"""GitHub agent node backed by the GitHub MCP server."""

import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from autoops.a2a.client import A2AClient
from autoops.state import AutoOpsState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GITHUB_MCP_SERVER = PROJECT_ROOT / "autoops" / "mcp" / "mcp_github.py"


def _select_read_tool(task: str) -> str:
    """Map a GitHub task to a read-only MCP tool."""
    normalized = task.lower()
    if "status" in normalized or "commit" in normalized or "repository" in normalized or "repo" in normalized:
        return "get_repo_status"
    return "list_open_prs"


def _is_issue_write(task: str) -> bool:
    """Return whether the task asks to create a GitHub issue."""
    normalized = task.lower()
    return "create" in normalized and "issue" in normalized


def _needs_code_review_delegation(task: str) -> bool:
    """Return whether a GitHub task should ask Code Review for help."""
    normalized = task.lower()
    return ("pr" in normalized or "pull request" in normalized) and any(
        signal in normalized for signal in ("review", "diff", "risk", "scan", "quality")
    )


async def _call_github_tool(tool_name: str, args: dict | None = None) -> str:
    """Call a GitHub MCP tool over stdio and return text content."""
    server_params = StdioServerParameters(
        command="python3",
        args=[str(GITHUB_MCP_SERVER)],
        env=os.environ.copy(),
        cwd=PROJECT_ROOT,
    )

    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(server_params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args or {})

    text_parts = [content.text for content in result.content if content.type == "text"]
    if text_parts:
        return "\n".join(text_parts)
    return json.dumps(result.model_dump(), indent=2)


async def _delegate_pr_analysis(task: str) -> dict:
    """Delegate PR/diff analysis to the Code Review A2A server."""
    base_url = os.getenv("CODEREVIEW_A2A_URL", "http://localhost:9003")
    client = A2AClient(bearer_token=os.getenv("A2A_BEARER_TOKEN"))
    return await client.delegate(
        base_url,
        "diff_summary",
        {
            "diff_text": task,
        },
    )


async def github_node(state: AutoOpsState) -> AutoOpsState:
    """Handle GitHub tasks using MCP tools."""
    task = state["current_task"]

    if _is_issue_write(task):
        return {
            "pending_approval": True,
            "write_approved": False,
            "approval_details": {
                "action": "Create GitHub issue requested by user task",
                "tool": "create_issue",
                "args": {
                    "title": task,
                    "body": "TODO: compose incident body from agent findings.",
                    "labels": [],
                },
                "agent": "github",
            },
            "agent_outputs": {
                **state["agent_outputs"],
                "github": "Prepared GitHub issue creation request. HITL approval wiring is required before calling create_issue.",
            },
        }

    if _needs_code_review_delegation(task):
        try:
            delegation = await _delegate_pr_analysis(task)
            return {
                "a2a_delegations": [
                    *state["a2a_delegations"],
                    {
                        "target_agent": "autoops-codereview",
                        "task_type": "diff_summary",
                        "status": delegation.get("status"),
                        "task_id": delegation.get("id"),
                    },
                ],
                "agent_outputs": {
                    **state["agent_outputs"],
                    "github": json.dumps(
                        {
                            "message": "Delegated PR analysis to Code Review Agent via A2A.",
                            "delegation": delegation,
                        },
                        indent=2,
                    ),
                },
            }
        except Exception as exc:
            return {
                "a2a_delegations": [
                    *state["a2a_delegations"],
                    {
                        "target_agent": "autoops-codereview",
                        "task_type": "diff_summary",
                        "status": "failed",
                        "error": str(exc),
                    },
                ],
                "agent_outputs": {
                    **state["agent_outputs"],
                    "github": f"Code Review A2A delegation failed; continuing with warning: {exc}",
                },
            }

    tool_name = _select_read_tool(task)
    output = await _call_github_tool(tool_name)

    return {
        "agent_outputs": {
            **state["agent_outputs"],
            "github": output,
        }
    }


async def github_write_node(state: AutoOpsState) -> AutoOpsState:
    """Execute an approved GitHub write operation."""
    if not state["write_approved"]:
        return {
            "pending_approval": False,
            "approval_details": None,
            "agent_outputs": {
                **state["agent_outputs"],
                "github_write": "GitHub write blocked because human approval was not recorded.",
            },
        }

    details = state["approval_details"]
    if not details:
        return {
            "error": "github_write reached without approval_details",
            "agent_outputs": {
                **state["agent_outputs"],
                "github_write": "No approval details were available.",
            },
        }

    if details["tool"] != "create_issue":
        return {
            "error": f"unsupported GitHub write tool: {details['tool']}",
            "agent_outputs": {
                **state["agent_outputs"],
                "github_write": f"Unsupported write tool: {details['tool']}",
            },
        }

    output = await _call_github_tool(details["tool"], details["args"])
    return {
        "pending_approval": False,
        "write_approved": False,
        "approval_details": None,
        "agent_outputs": {
            **state["agent_outputs"],
            "github_write": output,
        },
    }
