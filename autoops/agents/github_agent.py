"""GitHub agent node backed by the GitHub MCP server."""

import json
import os
import re
from pathlib import Path

from autoops.a2a.client import A2AClient
from autoops.mcp_client import call_mcp_tool
from autoops.state import AutoOpsState


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GITHUB_MCP_SERVER = PROJECT_ROOT / "autoops" / "mcp" / "mcp_github.py"
CLOUDWATCH_MCP_SERVER = PROJECT_ROOT / "autoops" / "mcp" / "mcp_cloudwatch.py"
CODEREVIEW_MCP_SERVER = PROJECT_ROOT / "autoops" / "mcp" / "mcp_codereview.py"
MONITORING_MCP_SERVER = PROJECT_ROOT / "autoops" / "mcp" / "mcp_monitoring.py"


def _select_read_tool(task: str) -> str:
    """Map a GitHub task to a read-only MCP tool."""
    tool_name, _ = _select_read_tool_and_args(task)
    return tool_name


def _select_read_tool_and_args(task: str) -> tuple[str, dict]:
    """Map a GitHub task to a read-only MCP tool and arguments."""
    normalized = task.lower()
    if "diff" in normalized and ("pr" in normalized or "pull request" in normalized):
        return "get_pr_diff", {"pr_number": _extract_pr_number(task)}
    if "status" in normalized or "commit" in normalized or "repository" in normalized or "repo" in normalized:
        return "get_repo_status", {}
    return "list_open_prs", {}


def _is_issue_write(task: str) -> bool:
    """Return whether the task asks to create a GitHub issue."""
    normalized = task.lower()
    return "create" in normalized and "issue" in normalized


def _is_pr_comment_write(task: str) -> bool:
    """Return whether the task asks to add a GitHub PR comment."""
    normalized = task.lower()
    has_pr = "pr" in normalized or "pull request" in normalized
    has_comment = "comment" in normalized or "review comment" in normalized
    has_write_intent = any(signal in normalized for signal in ("add", "create", "post", "write", "leave"))
    return has_pr and has_comment and has_write_intent


def _extract_pr_number(task: str) -> int:
    """Extract a pull request number from a natural-language task."""
    patterns = [
        r"(?:pr|pull request)\s*#?\s*(\d+)",
        r"#(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, task, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 1


def _extract_pr_comment(task: str) -> str:
    """Extract or build a pull-request comment from a natural-language task."""
    quoted = re.search(r'"([^"]+)"|' "'([^']+)'", task)
    if quoted:
        return next(group for group in quoted.groups() if group)

    prefixes = [
        r".*?(?:comment|review comment)\s+(?:on|to|for)?\s*(?:pr|pull request)?\s*#?\d*[:\-]?\s*",
        r".*?(?:add|create|post|write|leave)\s+",
    ]
    comment = task
    for prefix in prefixes:
        comment = re.sub(prefix, "", comment, flags=re.IGNORECASE).strip()
    return comment or task


def _pr_comment_approval_details(task: str) -> dict:
    """Build approval details for a PR comment write."""
    pr_number = _extract_pr_number(task)
    comment = _extract_pr_comment(task)
    return {
        "action": f"Add GitHub PR comment to PR #{pr_number}",
        "tool": "add_pr_comment",
        "args": {
            "pr_number": pr_number,
            "comment": comment,
        },
        "agent": "github",
    }


def _is_incident_issue_task(task: str) -> bool:
    """Return whether an issue request asks AutoOps to triage incident context."""
    normalized = task.lower()
    incident_signals = (
        "incident",
        "triage",
        "outage",
        "error rate",
        "spike",
        "spiked",
        "alarm",
        "latency",
        "degraded",
    )
    return _is_issue_write(task) and any(signal in normalized for signal in incident_signals)


def _extract_service_name(task: str) -> str:
    """Extract a service-like name from a natural-language task."""
    match = re.search(r"\b([\w-]+-service)\b", task)
    if match:
        return match.group(1)
    return "checkout-service"


def _truncate_text(value: str, max_chars: int = 4000) -> str:
    """Keep issue bodies readable when tool payloads are large."""
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "\n...[truncated]"


def _issue_body(task: str, incident_context: dict | None = None) -> str:
    """Build a concise issue body from the user request."""
    lines = [
        "AutoOps prepared this issue from an approved operator request.",
        "",
        "Request:",
        task,
    ]

    if incident_context:
        lines.extend(
            [
                "",
                "Incident context:",
                f"- Service: {incident_context['service']}",
                "",
                "Monitoring summary:",
                "```json",
                _truncate_text(incident_context.get("monitoring_summary", "not collected")),
                "```",
                "",
                "CloudWatch error-rate data:",
                "```json",
                _truncate_text(incident_context.get("cloudwatch_error_rate", "not collected")),
                "```",
                "",
                "GitHub repository context:",
                "```json",
                _truncate_text(incident_context.get("github_repo_status", "not collected")),
                "```",
                "",
                "Code review findings:",
                "```json",
                _truncate_text(incident_context.get("code_review_findings", "not collected")),
                "```",
            ]
        )

    lines.extend(
        [
            "",
            "Next steps:",
            "- Confirm affected service, environment, and severity.",
            "- Review related logs, alarms, metrics, commits, PRs, or deployment context.",
            "- Assign an owner before starting remediation.",
        ]
    )
    return "\n".join(lines)


def _needs_code_review_delegation(task: str) -> bool:
    """Return whether a GitHub task should ask Code Review for help."""
    normalized = task.lower()
    return ("pr" in normalized or "pull request" in normalized) and any(
        signal in normalized for signal in ("review", "risk", "scan", "quality")
    )


async def _call_github_tool(tool_name: str, args: dict | None = None) -> str:
    """Call a GitHub MCP tool over stdio and return text content."""
    return await _call_mcp_tool(GITHUB_MCP_SERVER, tool_name, args)


async def _call_cloudwatch_tool(tool_name: str, args: dict | None = None) -> str:
    """Call a CloudWatch MCP tool over stdio and return text content."""
    return await _call_mcp_tool(CLOUDWATCH_MCP_SERVER, tool_name, args)


async def _call_codereview_tool(tool_name: str, args: dict | None = None) -> str:
    """Call a Code Review MCP tool over stdio and return text content."""
    return await _call_mcp_tool(CODEREVIEW_MCP_SERVER, tool_name, args)


async def _call_monitoring_tool(tool_name: str, args: dict | None = None) -> str:
    """Call a Monitoring MCP tool over stdio and return text content."""
    return await _call_mcp_tool(MONITORING_MCP_SERVER, tool_name, args)


async def _call_mcp_tool(server_path: Path, tool_name: str, args: dict | None = None) -> str:
    """Call an MCP tool over stdio and return text content."""
    url_env_var = {
        GITHUB_MCP_SERVER: "GITHUB_MCP_URL",
        CLOUDWATCH_MCP_SERVER: "CLOUDWATCH_MCP_URL",
        CODEREVIEW_MCP_SERVER: "CODEREVIEW_MCP_URL",
        MONITORING_MCP_SERVER: "MONITORING_MCP_URL",
    }[server_path]
    default_sse_url = {
        GITHUB_MCP_SERVER: "http://localhost:8001/sse",
        CLOUDWATCH_MCP_SERVER: "http://localhost:8002/sse",
        CODEREVIEW_MCP_SERVER: "http://localhost:8003/sse",
        MONITORING_MCP_SERVER: "http://localhost:8004/sse",
    }[server_path]

    return await call_mcp_tool(
        server_path=server_path,
        tool_name=tool_name,
        args=args,
        agent="github",
        url_env_var=url_env_var,
        default_sse_url=default_sse_url,
        project_root=PROJECT_ROOT,
    )


async def _collect_incident_context(task: str) -> dict:
    """Collect read-only incident context before preparing a GitHub issue."""
    service_name = _extract_service_name(task)
    context = {"service": service_name}

    try:
        context["monitoring_summary"] = await _call_monitoring_tool(
            "get_incident_summary",
            {"service_name": service_name},
        )
    except Exception as exc:
        context["monitoring_summary"] = json.dumps({"error": str(exc)}, indent=2)

    try:
        context["cloudwatch_error_rate"] = await _call_cloudwatch_tool(
            "get_metrics",
            {
                "namespace": os.getenv("MONITORING_METRIC_NAMESPACE", "AutoOps/Services"),
                "metric_name": os.getenv("MONITORING_ERROR_RATE_METRIC", "ErrorRate"),
                "dimensions": {
                    os.getenv("MONITORING_SERVICE_DIMENSION", "ServiceName"): service_name,
                },
                "minutes": 60,
            },
        )
    except Exception as exc:
        context["cloudwatch_error_rate"] = json.dumps({"error": str(exc)}, indent=2)

    try:
        context["github_repo_status"] = await _call_github_tool("get_repo_status")
    except Exception as exc:
        context["github_repo_status"] = json.dumps({"error": str(exc)}, indent=2)

    try:
        context["code_review_findings"] = await _call_codereview_tool(
            "run_security_scan",
            {"repo_path": "."},
        )
    except Exception as exc:
        context["code_review_findings"] = json.dumps({"error": str(exc)}, indent=2)

    return context


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

    if _is_pr_comment_write(task):
        details = _pr_comment_approval_details(task)
        return {
            "pending_approval": True,
            "write_approved": False,
            "approval_details": details,
            "agent_outputs": {
                **state["agent_outputs"],
                "github": "Prepared GitHub PR comment request. HITL approval is required before calling add_pr_comment.",
            },
        }

    if _is_issue_write(task):
        incident_context = await _collect_incident_context(task) if _is_incident_issue_task(task) else None
        return {
            "pending_approval": True,
            "write_approved": False,
            "approval_details": {
                "action": "Create GitHub issue requested by user task",
                "tool": "create_issue",
                "args": {
                    "title": task,
                    "body": _issue_body(task, incident_context),
                    "labels": [],
                },
                "agent": "github",
            },
            "agent_outputs": {
                **state["agent_outputs"],
                "github": (
                    "Prepared incident issue creation request with read-only context. "
                    "HITL approval is required before calling create_issue."
                    if incident_context
                    else "Prepared GitHub issue creation request. HITL approval is required before calling create_issue."
                ),
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

    tool_name, args = _select_read_tool_and_args(task)
    output = await _call_github_tool(tool_name, args)

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

    if details["tool"] not in {"create_issue", "add_pr_comment"}:
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
