"""Observability for AutoOps: LangSmith tracing + Logfire spans.

AutoOps has two complementary observability layers, exactly as required by
PRD Section 8:

1. LangSmith  — traces the *LangGraph* execution (which node ran, in what
   order, token cost, inputs/outputs). Driven entirely by LangChain's own
   environment variables (LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY). We only
   need to attach run_name + tags + metadata to each graph invocation; see
   `graph_config()`.

2. Logfire    — structured, OpenTelemetry-based spans around the *side effects*
   the graph performs: every MCP tool call and every A2A delegation, each with
   a duration. This is what tells you "the github MCP create_issue call took
   840ms" or "the A2A delegate to codereview failed after 5s".

Both layers are optional: with no credentials configured, everything degrades
to a no-op so local development and tests stay fast and dependency-light.
"""

import os
from contextlib import contextmanager
from time import perf_counter
from typing import Any

_LOGFIRE_READY = False


def configure_observability() -> None:
    """Initialise Logfire once, based on environment configuration.

    Resolution order:
    - LOGFIRE_TOKEN set            -> send spans to the Logfire cloud.
    - AUTOOPS_LOGFIRE_CONSOLE=true -> print spans to the console (handy for
                                      local demos without a Logfire account).
    - neither                      -> Logfire stays off; all helpers no-op.

    Idempotent: safe to call multiple times (only configures once).
    """
    global _LOGFIRE_READY
    if _LOGFIRE_READY:
        return

    token = os.getenv("LOGFIRE_TOKEN")
    console = os.getenv("AUTOOPS_LOGFIRE_CONSOLE", "false").lower() == "true"
    if not token and not console:
        return

    try:
        import logfire
    except ImportError:
        return

    logfire.configure(
        token=token,
        send_to_logfire=bool(token),
        service_name="autoops",
        console=False if token else None,  # None = default console output
    )
    _LOGFIRE_READY = True


def graph_config(session_id: str, run_name: str = "autoops-run", agent_name: str = "supervisor") -> dict:
    """Build a LangGraph config with LangSmith-friendly tracing metadata.

    `run_name` names the trace, `tags` make runs filterable in the LangSmith
    UI, and `thread_id` ties checkpoints (and traces) to one session. These are
    inert unless LangSmith tracing is enabled via the LANGCHAIN_* env vars.
    """
    return {
        "configurable": {"thread_id": session_id},
        "run_name": run_name,
        "tags": ["autoops", agent_name, session_id],
        "metadata": {
            "session_id": session_id,
            "agent": agent_name,
        },
    }


@contextmanager
def tool_span(tool_name: str, agent: str, **attributes: Any):
    """Open a Logfire span around a tool call or A2A delegation.

    Records a `duration_ms` attribute on the span. When Logfire is not
    configured this is a zero-overhead no-op, so callers can instrument freely
    without making observability mandatory.
    """
    start = perf_counter()
    if not _LOGFIRE_READY:
        yield
        return

    import logfire

    with logfire.span(f"tool:{tool_name}", tool_name=tool_name, agent=agent, **attributes) as span:
        try:
            yield
        finally:
            span.set_attribute("duration_ms", round((perf_counter() - start) * 1000, 2))


def log_error(message: str, *, session_id: str, active_agent: str, **attributes: Any) -> None:
    """Emit a structured error log correlated by session_id + active_agent.

    Per PRD Section 8, error logs must carry these two fields so a failure can
    be traced back to the session and the agent that produced it. No-op when
    Logfire is not configured.
    """
    if not _LOGFIRE_READY:
        return

    import logfire

    logfire.error(message, session_id=session_id, active_agent=active_agent, **attributes)
