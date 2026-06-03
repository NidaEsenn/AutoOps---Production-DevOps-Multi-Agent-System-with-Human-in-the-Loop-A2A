"""FastMCP server exposing service monitoring tools."""

import json
import os
from datetime import UTC, datetime, timedelta

from fastmcp import FastMCP


mcp = FastMCP("monitoring-agent")


SERVICE_PROFILES = {
    "checkout-service": {
        "status": "degraded",
        "error_rate_percent": 3.8,
        "p95_latency_ms": 620,
        "active_alarms": ["CheckoutHighErrorRate"],
    },
    "payments-service": {
        "status": "healthy",
        "error_rate_percent": 0.1,
        "p95_latency_ms": 180,
        "active_alarms": [],
    },
    "inventory-service": {
        "status": "healthy",
        "error_rate_percent": 0.3,
        "p95_latency_ms": 240,
        "active_alarms": [],
    },
}


def _error_response(tool: str, error: Exception) -> str:
    """Return a structured tool error payload."""
    return json.dumps({"tool": tool, "error": str(error)}, indent=2)


def _profile_for(service_name: str) -> dict:
    """Return service health profile, falling back to a neutral unknown service."""
    return SERVICE_PROFILES.get(
        service_name,
        {
            "status": "unknown",
            "error_rate_percent": None,
            "p95_latency_ms": None,
            "active_alarms": [],
        },
    )


def _now() -> datetime:
    """Return current UTC time; isolated for easier future testing."""
    return datetime.now(UTC)


@mcp.tool()
async def get_service_health(service_name: str) -> str:
    """Return current health signals for a service.

    This first implementation uses deterministic local demo data. CloudWatch
    metrics can replace this data source later without changing the agent API.
    """
    try:
        profile = _profile_for(service_name)
        return json.dumps(
            {
                "service": service_name,
                "status": profile["status"],
                "error_rate_percent": profile["error_rate_percent"],
                "p95_latency_ms": profile["p95_latency_ms"],
                "active_alarms": profile["active_alarms"],
                "checked_at": _now().isoformat(),
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("get_service_health", exc)


@mcp.tool()
async def get_deployment_history(service_name: str, n_recent: int = 5) -> str:
    """Return recent deployment events for a service."""
    try:
        now = _now()
        deployments = []
        for index in range(max(0, n_recent)):
            deployed_at = now - timedelta(hours=6 * index + 1)
            deployments.append(
                {
                    "service": service_name,
                    "version": f"2026.05.{31 - index}",
                    "environment": "production",
                    "deployed_at": deployed_at.isoformat(),
                    "status": "succeeded",
                }
            )

        return json.dumps(
            {
                "service": service_name,
                "deployments": deployments,
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("get_deployment_history", exc)


@mcp.tool()
async def get_incident_summary(service_name: str) -> str:
    """Return an incident-style summary combining health and deployment context."""
    try:
        profile = _profile_for(service_name)
        health_status = profile["status"]
        active_alarms = profile["active_alarms"]
        severity = "high" if health_status == "degraded" and active_alarms else "low"

        return json.dumps(
            {
                "service": service_name,
                "severity": severity,
                "summary": _summary_sentence(service_name, profile),
                "health": {
                    "status": health_status,
                    "error_rate_percent": profile["error_rate_percent"],
                    "p95_latency_ms": profile["p95_latency_ms"],
                    "active_alarms": active_alarms,
                },
                "recommended_next_steps": _next_steps(profile),
                "generated_at": _now().isoformat(),
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("get_incident_summary", exc)


def _summary_sentence(service_name: str, profile: dict) -> str:
    """Build a short incident summary from a health profile."""
    if profile["status"] == "unknown":
        return f"No monitoring profile exists yet for {service_name}."
    if profile["status"] == "degraded":
        return (
            f"{service_name} is degraded with error rate "
            f"{profile['error_rate_percent']}% and p95 latency {profile['p95_latency_ms']} ms."
        )
    return (
        f"{service_name} is healthy with error rate "
        f"{profile['error_rate_percent']}% and p95 latency {profile['p95_latency_ms']} ms."
    )


def _next_steps(profile: dict) -> list[str]:
    """Suggest basic operator follow-ups for the current health profile."""
    if profile["status"] == "degraded":
        return [
            "Inspect recent deployments for the service.",
            "Review error logs around the start of the alarm window.",
            "Check recent GitHub commits touching the service.",
        ]
    if profile["status"] == "unknown":
        return ["Configure monitoring data source for this service."]
    return ["Continue normal monitoring."]


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        port = int(os.getenv("MONITORING_MCP_PORT", os.getenv("MCP_PORT", "8004")))
        mcp.run(transport="sse", host="0.0.0.0", port=port, show_banner=False)
    else:
        mcp.run(show_banner=False)

