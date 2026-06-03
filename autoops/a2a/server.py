"""FastAPI A2A server for the Code Review agent."""

import json
import os
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException

from autoops.a2a.models import A2ATask, AgentAuthentication, AgentCapabilities, AgentCard
from autoops.agents.codereview_agent import _call_codereview_tool


app = FastAPI(title="AutoOps Code Review A2A Server")


def _agent_card() -> AgentCard:
    """Build the Code Review Agent Card."""
    return AgentCard(
        name="autoops-codereview",
        version="1.0.0",
        description="Performs static analysis, security scanning, and diff summarisation on code changes.",
        url=os.getenv("CODEREVIEW_A2A_URL", "http://localhost:9003"),
        capabilities=AgentCapabilities(tasks=["lint", "security_scan", "diff_summary"]),
        authentication=AgentAuthentication(type="bearer" if os.getenv("A2A_BEARER_TOKEN") else "none"),
    )


def _check_auth(authorization: str | None) -> None:
    """Validate optional bearer authentication."""
    expected_token = os.getenv("A2A_BEARER_TOKEN")
    if not expected_token:
        return
    if authorization != f"Bearer {expected_token}":
        raise HTTPException(status_code=401, detail="invalid A2A bearer token")


@app.get("/.well-known/agent.json")
async def agent_card() -> dict:
    """Return this A2A server's Agent Card."""
    return _agent_card().model_dump()


@app.post("/tasks")
async def submit_task(task: A2ATask, authorization: str | None = Header(default=None)) -> dict:
    """Execute an A2A task and return its completed result."""
    _check_auth(authorization)

    task.status = "working"
    task.updated_at = datetime.now(UTC)

    try:
        tool_name, args = _map_task_to_tool(task)
        raw_output = await _call_codereview_tool(tool_name, args)
        task.output = _parse_tool_output(raw_output)
        task.status = "completed"
    except Exception as exc:
        task.status = "failed"
        task.error = str(exc)
    finally:
        task.updated_at = datetime.now(UTC)

    return task.model_dump()


def _map_task_to_tool(task: A2ATask) -> tuple[str, dict]:
    """Map A2A task types to Code Review MCP tools."""
    if task.type == "diff_summary":
        return "get_diff_summary", {"diff_text": task.input.get("diff_text", "")}
    if task.type == "lint":
        return "run_linter", {"file_path": task.input.get("file_path", "autoops/supervisor.py")}
    if task.type == "security_scan":
        return "run_security_scan", {"repo_path": task.input.get("repo_path", ".")}
    raise ValueError(f"unsupported A2A task type: {task.type}")


def _parse_tool_output(raw_output: str) -> dict:
    """Parse JSON tool output, preserving raw text if needed."""
    try:
        parsed = json.loads(raw_output)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except json.JSONDecodeError:
        return {"result": raw_output}

