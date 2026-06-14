"""FastAPI wrapper around the AutoOps graph."""

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from autoops.hitl import DEFAULT_CHECKPOINT_DB_PATH, WRITE_NODES
from autoops.observability import graph_config, log_error
from autoops.state import initial_state
from autoops.supervisor import build_graph


app = FastAPI(title="AutoOps API", version="0.1.0")


class RunRequest(BaseModel):
    task: str = Field(min_length=1)
    session_id: str = "api-session"


class ApproveRequest(BaseModel):
    session_id: str
    approved: bool


def _checkpoint_path() -> str:
    """Return the checkpoint database path used by graph API requests."""
    return os.getenv("CHECKPOINT_DB_PATH", DEFAULT_CHECKPOINT_DB_PATH)


def _graph_config(session_id: str) -> dict:
    """Build LangGraph config for checkpointed execution."""
    return graph_config(session_id, run_name="autoops-api-run", agent_name="supervisor")


def _response_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a stable API response from graph state."""
    if state.get("pending_approval"):
        return {
            "status": "approval_required",
            "active_agent": state.get("active_agent"),
            "approval_details": state.get("approval_details"),
            "agent_outputs": state.get("agent_outputs", {}),
        }

    return {
        "status": "complete" if not state.get("error") else "failed",
        "active_agent": state.get("active_agent"),
        "agent_outputs": state.get("agent_outputs", {}),
        "a2a_delegations": state.get("a2a_delegations", []),
        "error": state.get("error"),
    }


@app.post("/run")
async def run_task(request: RunRequest) -> dict[str, Any]:
    """Start an AutoOps graph task."""
    try:
        async with AsyncSqliteSaver.from_conn_string(_checkpoint_path()) as checkpointer:
            graph = build_graph(checkpointer=checkpointer, interrupt_before=WRITE_NODES)
            result = await graph.ainvoke(initial_state(request.task, request.session_id), config=_graph_config(request.session_id))
    except Exception as exc:
        log_error(f"AutoOps run failed: {exc}", session_id=request.session_id, active_agent="supervisor")
        raise
    if result.get("error"):
        log_error(result["error"], session_id=request.session_id, active_agent=result.get("active_agent") or "supervisor")
    return _response_from_state(result)


@app.post("/approve")
async def approve_task(request: ApproveRequest) -> dict[str, Any]:
    """Resume a paused graph after human approval or rejection."""
    if not request.approved:
        return {
            "status": "cancelled",
            "session_id": request.session_id,
            "agent_outputs": {
                "github_write": "Cancelled by human reviewer. No GitHub write was executed.",
            },
        }

    async with AsyncSqliteSaver.from_conn_string(_checkpoint_path()) as checkpointer:
        graph = build_graph(checkpointer=checkpointer, interrupt_before=WRITE_NODES)
        try:
            result = await graph.ainvoke(
                Command(update={"write_approved": True}, resume=True),
                config=_graph_config(request.session_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _response_from_state(result)


@app.get("/agents")
async def list_agents() -> list[dict[str, Any]]:
    """List configured agents and their public capabilities."""
    codereview_url = os.getenv("CODEREVIEW_A2A_URL", "http://localhost:9003")
    return [
        {
            "name": "autoops-github",
            "type": "langgraph-node",
            "status": "configured",
            "capabilities": ["list_open_prs", "get_repo_status", "get_pr_diff", "create_issue", "add_pr_comment"],
        },
        {
            "name": "autoops-cloudwatch",
            "type": "langgraph-node",
            "status": "configured",
            "capabilities": ["get_log_events", "list_alarms", "get_metrics", "describe_recent_deployments"],
        },
        {
            "name": "autoops-codereview",
            "type": "a2a-server",
            "status": "configured",
            "url": codereview_url,
            "capabilities": ["lint", "security_scan", "diff_summary"],
        },
        {
            "name": "autoops-monitoring",
            "type": "langgraph-node",
            "status": "configured",
            "capabilities": ["get_service_health", "get_deployment_history", "get_incident_summary"],
        },
    ]
