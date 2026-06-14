"""Amazon Bedrock AgentCore entrypoint for AutoOps (framework-agnostic deployment).

This wraps the LangGraph graph so AutoOps can run *inside* the AgentCore
Runtime. The runtime invokes the entrypoint over HTTP (POST /invocations) with a
JSON payload; we run the graph and return a JSON-serialisable result. This is the
"Integrating LangGraph with AgentCore" piece of the curriculum.

Local testing (no AWS needed):
    python -m autoops.agentcore_app          # serves on :8080
    # then, in another shell:
    curl -s localhost:8080/invocations \\
         -H 'content-type: application/json' \\
         -d '{"task": "show health for checkout-service"}'

Deploy (later, costs credits):
    agentcore configure -e autoops/agentcore_app.py
    agentcore deploy
"""

import os
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from autoops.hitl import WRITE_NODES
from autoops.observability import graph_config, log_error
from autoops.state import initial_state
from autoops.supervisor import build_graph

app = BedrockAgentCoreApp()

# The AgentCore runtime filesystem is read-only except for /tmp, so the HITL
# checkpoint DB must live there. Overridable via CHECKPOINT_DB_PATH.
DEFAULT_CHECKPOINT_DB_PATH = "/tmp/autoops_checkpoints.db"


def _result_payload(state: dict[str, Any]) -> dict[str, Any]:
    """Shape graph state into a stable JSON response (mirrors the REST API)."""
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


@app.entrypoint
async def invoke(payload: dict) -> dict:
    """AgentCore entrypoint: run an AutoOps task from the request payload.

    Payload: {"task": "<natural language task>", "session_id": "<optional>"}.
    Write actions pause and return status="approval_required" instead of
    blocking on a terminal, since the runtime has no interactive stdin.
    """
    task = payload.get("task") or payload.get("prompt")
    session_id = payload.get("session_id", "agentcore-session")
    if not task:
        return {"status": "failed", "error": "Payload must include 'task' (or 'prompt')."}

    checkpoint_path = os.getenv("CHECKPOINT_DB_PATH", DEFAULT_CHECKPOINT_DB_PATH)
    try:
        async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
            graph = build_graph(checkpointer=checkpointer, interrupt_before=WRITE_NODES)
            result = await graph.ainvoke(
                initial_state(task, session_id),
                config=graph_config(session_id, run_name="autoops-agentcore-run"),
            )
    except Exception as exc:  # surface failures as a structured response, not a 500
        log_error(f"AgentCore run failed: {exc}", session_id=session_id, active_agent="supervisor")
        return {"status": "failed", "error": str(exc)}

    return _result_payload(result)


if __name__ == "__main__":
    app.run(port=int(os.getenv("AGENTCORE_PORT", "8080")))
