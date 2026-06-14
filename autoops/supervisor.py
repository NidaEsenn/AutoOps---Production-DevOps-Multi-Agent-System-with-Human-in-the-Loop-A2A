"""Supervisor routing and LangGraph definition for AutoOps."""

import os
from dataclasses import dataclass
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from autoops.agents.cloudwatch_agent import cloudwatch_node
from autoops.agents.codereview_agent import codereview_node
from autoops.agents.github_agent import github_node, github_write_node
from autoops.agents.monitoring_agent import monitoring_node
from autoops.observability import graph_config
from autoops.state import AutoOpsState


AgentName = Literal["github", "cloudwatch", "codereview", "monitoring", "end"]


@dataclass(frozen=True)
class RoutingDecision:
    next_agent: AgentName
    reasoning: str
    sub_task: str


ROUTING_KEYWORDS: list[tuple[AgentName, tuple[str, ...], str]] = [
    (
        "cloudwatch",
        ("logs", "alarm", "metric", "metrics", "error rate", "latency", "cloudwatch"),
        "The request mentions logs, alarms, metrics, latency, or CloudWatch.",
    ),
    (
        "codereview",
        ("security", "lint", "vulnerability", "sast", "static analysis", "scan"),
        "The request asks for code quality, security, or static analysis.",
    ),
    (
        "monitoring",
        ("health", "uptime", "deployment history", "incident", "status page", "status"),
        "The request mentions service health, incidents, deployments, or status.",
    ),
    (
        "github",
        ("pr", "pull request", "issue", "commit", "branch", "merge", "repository", "repo", "git"),
        "The request mentions repository, issue, PR, or Git workflow.",
    ),
]


def decide_route(task: str) -> RoutingDecision:
    """Classify a task using the PRD keyword routing table."""
    normalized = task.lower()

    if "create" in normalized and "issue" in normalized:
        return RoutingDecision(
            next_agent="github",
            reasoning="The request asks to create a GitHub issue.",
            sub_task=task,
        )

    for agent, keywords, reasoning in ROUTING_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return RoutingDecision(
                next_agent=agent,
                reasoning=reasoning,
                sub_task=task,
            )

    return RoutingDecision(
        next_agent="end",
        reasoning="The request is ambiguous and does not match a v1 AutoOps agent.",
        sub_task="Ask the user to clarify whether this is GitHub, CloudWatch, code review, or monitoring work.",
    )


class RoutingDecisionModel(BaseModel):
    """Structured-output schema the LLM fills in for routing (PRD 4.2)."""

    next_agent: Literal["github", "cloudwatch", "codereview", "monitoring", "end"]
    reasoning: str = Field(description="One sentence explaining the routing choice.")
    sub_task: str = Field(description="What this specific agent should accomplish.")


ROUTING_SYSTEM_PROMPT = """You are the AutoOps supervisor for a DevOps multi-agent system.
Classify the user's request and route it to exactly one specialist agent.

Routing table:
- github     : pull requests, issues, commits, branches, merges, repository/Git workflows.
- cloudwatch : logs, alarms, metrics, error rate, latency, CloudWatch queries.
- codereview : security scans, linting, vulnerabilities, SAST, static analysis.
- monitoring : service health, uptime, deployment history, incident summaries, status.
- end        : the request is ambiguous or not a DevOps task; ask the user to clarify.

Rules:
- Creating or filing a GitHub issue (even from an incident) routes to "github".
- If the request does not clearly match a specialist, choose "end".
- Always provide a one-sentence reasoning and a concrete sub_task for the chosen agent."""


def _build_router_llm():
    """Return a Groq chat model for routing, or None if not configured."""
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key or api_key.startswith("REPLACE_WITH"):
        return None
    try:
        from langchain_groq import ChatGroq
    except ImportError:
        return None
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    return ChatGroq(model=model, temperature=0)


async def llm_route(task: str) -> RoutingDecision | None:
    """Route via the LLM with structured output; None if unavailable or it fails."""
    llm = _build_router_llm()
    if llm is None:
        return None
    try:
        structured = llm.with_structured_output(RoutingDecisionModel)
        result = await structured.ainvoke(
            [("system", ROUTING_SYSTEM_PROMPT), ("human", task)]
        )
        return RoutingDecision(
            next_agent=result.next_agent,
            reasoning=result.reasoning,
            sub_task=result.sub_task or task,
        )
    except Exception:
        # Any LLM/network/parse failure falls back to deterministic routing.
        return None


async def supervisor_node(state: AutoOpsState) -> AutoOpsState:
    """Route the current task to the next specialist agent.

    Uses the LLM router when GROQ_API_KEY is configured, otherwise falls back to
    deterministic keyword routing so the graph always works offline and in tests.
    """
    decision = await llm_route(state["current_task"]) or decide_route(state["current_task"])
    return {
        "active_agent": decision.next_agent,
        "current_task": decision.sub_task,
        "agent_outputs": {
            **state["agent_outputs"],
            "supervisor": f"{decision.next_agent}: {decision.reasoning}",
        },
    }


def route_after_supervisor(state: AutoOpsState) -> str:
    """Return the next node name after supervisor classification."""
    return state["active_agent"]


def route_after_github(state: AutoOpsState) -> str:
    """Route GitHub results to a write node only when approval is pending."""
    if state["pending_approval"]:
        return "github_write"
    return "mark_end"


async def clarify_node(state: AutoOpsState) -> AutoOpsState:
    """Handle ambiguous tasks without silently choosing an agent."""
    return {
        "agent_outputs": {
            **state["agent_outputs"],
            "end": "I need a clearer DevOps task before choosing an agent.",
        }
    }


async def end_node(state: AutoOpsState) -> AutoOpsState:
    """Mark the graph as complete."""
    return {"active_agent": "end"}


def build_graph(checkpointer=None, interrupt_before: list[str] | None = None):
    """Build the Session A LangGraph with mock specialist agents."""
    builder = StateGraph(AutoOpsState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("github", github_node)
    builder.add_node("github_write", github_write_node)
    builder.add_node("cloudwatch", cloudwatch_node)
    builder.add_node("codereview", codereview_node)
    builder.add_node("monitoring", monitoring_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("mark_end", end_node)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "github": "github",
            "cloudwatch": "cloudwatch",
            "codereview": "codereview",
            "monitoring": "monitoring",
            "end": "clarify",
        },
    )
    builder.add_conditional_edges(
        "github",
        route_after_github,
        {
            "github_write": "github_write",
            "mark_end": "mark_end",
        },
    )
    builder.add_edge("github_write", "mark_end")
    builder.add_edge("cloudwatch", "mark_end")
    builder.add_edge("codereview", "mark_end")
    builder.add_edge("monitoring", "mark_end")
    builder.add_edge("clarify", "mark_end")
    builder.add_edge("mark_end", END)

    return builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)


async def run_graph(state: AutoOpsState) -> AutoOpsState:
    """Run the compiled AutoOps graph."""
    graph = build_graph()
    return await graph.ainvoke(state, config=graph_config(state["session_id"]))
