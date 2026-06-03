"""Shared state for AutoOps graph execution."""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages


class ApprovalDetails(TypedDict):
    action: str
    tool: str
    args: dict
    agent: str


class AutoOpsState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    current_task: str
    active_agent: Literal[
        "github",
        "cloudwatch",
        "codereview",
        "monitoring",
        "supervisor",
        "end",
    ]
    pending_approval: bool
    write_approved: bool
    approval_details: ApprovalDetails | None
    agent_outputs: dict[str, str]
    a2a_delegations: list[dict]
    error: str | None
    session_id: str


def initial_state(task: str, session_id: str = "local-dev") -> AutoOpsState:
    """Create the starting state for a CLI task."""
    return {
        "messages": [HumanMessage(content=task)],
        "current_task": task,
        "active_agent": "supervisor",
        "pending_approval": False,
        "write_approved": False,
        "approval_details": None,
        "agent_outputs": {},
        "a2a_delegations": [],
        "error": None,
        "session_id": session_id,
    }
