"""Human-in-the-loop approval handling for AutoOps."""

import json
import os

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from autoops.state import AutoOpsState
from autoops.supervisor import build_graph


WRITE_NODES = ["github_write"]
DEFAULT_CHECKPOINT_DB_PATH = "autoops_checkpoints.db"


def _graph_config(session_id: str) -> dict:
    """Build LangGraph config for checkpointed execution."""
    return {"configurable": {"thread_id": session_id}}


def _print_approval(details: dict) -> None:
    """Render approval details in the terminal."""
    print("\nAPPROVAL REQUIRED")
    print(f"Action : {details['action']}")
    print(f"Tool   : {details['tool']}")
    print("Args   :")
    print(json.dumps(details["args"], indent=2))


async def run_with_approval_loop(state: AutoOpsState) -> AutoOpsState:
    """Run the graph and pause for human approval before write nodes."""
    db_path = os.getenv("CHECKPOINT_DB_PATH", DEFAULT_CHECKPOINT_DB_PATH)
    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = build_graph(
            checkpointer=checkpointer,
            interrupt_before=WRITE_NODES,
        )
        config = _graph_config(state["session_id"])
        result = await graph.ainvoke(state, config=config)

        if not result.get("pending_approval"):
            return result

        details = result["approval_details"]
        if not details:
            return {
                **result,
                "error": "Graph paused for approval without approval_details.",
            }

        while True:
            _print_approval(details)
            response = input("\nApprove? [yes / no / show-full]: ").strip().lower()

            if response == "show-full":
                print(json.dumps(details, indent=2))
                continue

            if response == "yes":
                return await graph.ainvoke(
                    Command(update={"write_approved": True}, resume=True),
                    config=config,
                )

            if response == "no":
                return {
                    **result,
                    "active_agent": "end",
                    "pending_approval": False,
                    "write_approved": False,
                    "approval_details": None,
                    "agent_outputs": {
                        **result["agent_outputs"],
                        "github_write": "Cancelled by human reviewer. No GitHub write was executed.",
                    },
                }

            print("Please type yes, no, or show-full.")
