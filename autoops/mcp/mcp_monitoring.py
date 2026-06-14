"""FastMCP server exposing service monitoring tools."""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastmcp import FastMCP


mcp = FastMCP("monitoring-agent")


DEFAULT_METRIC_NAMESPACE = "AutoOps/Services"
DEFAULT_ERROR_RATE_METRIC = "ErrorRate"
DEFAULT_LATENCY_METRIC = "Latency"
DEFAULT_DIMENSION_NAME = "ServiceName"
DEFAULT_DEPLOYMENT_LOG_GROUP = "/aws/autoops/deployments"


def _error_response(tool: str, error: Exception) -> str:
    """Return a structured tool error payload."""
    return json.dumps(
        {
            "tool": tool,
            "error": str(error),
            "hint": "Check AWS credentials, AWS_DEFAULT_REGION, CloudWatch metrics, alarms, and deployment log group.",
        },
        indent=2,
    )


def _client(service_name: str):
    """Create a boto3 client using the default AWS environment/session."""
    return boto3.client(service_name, region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


def _now() -> datetime:
    """Return current UTC time; isolated for easier future testing."""
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    """Serialize datetimes and other AWS response values to JSON."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _metric_namespace() -> str:
    """Return the CloudWatch namespace used for service metrics."""
    return os.getenv("MONITORING_METRIC_NAMESPACE", DEFAULT_METRIC_NAMESPACE)


def _dimension_name() -> str:
    """Return the CloudWatch dimension name used to identify services."""
    return os.getenv("MONITORING_SERVICE_DIMENSION", DEFAULT_DIMENSION_NAME)


def _metric_name(env_var: str, default: str) -> str:
    """Return a CloudWatch metric name from environment or default."""
    return os.getenv(env_var, default)


def _threshold(env_var: str, default: float) -> float:
    """Return a numeric threshold from environment or default."""
    try:
        return float(os.getenv(env_var, str(default)))
    except ValueError:
        return default


def _metric_dimensions(service_name: str) -> list[dict[str, str]]:
    """Build CloudWatch dimensions for a service metric."""
    return [{"Name": _dimension_name(), "Value": service_name}]


def _latest_metric_value(response: dict, stat: str) -> float | None:
    """Return the most recent datapoint value for a CloudWatch metric."""
    datapoints = sorted(response.get("Datapoints", []), key=lambda point: point["Timestamp"])
    if not datapoints:
        return None
    value = datapoints[-1].get(stat)
    return float(value) if value is not None else None


def _get_metric_value(
    cloudwatch,
    service_name: str,
    metric_name: str,
    stat: str,
    minutes: int = 60,
    period: int = 300,
) -> float | None:
    """Fetch the latest CloudWatch metric value for a service."""
    end_time = _now()
    start_time = end_time - timedelta(minutes=minutes)
    response = cloudwatch.get_metric_statistics(
        Namespace=_metric_namespace(),
        MetricName=metric_name,
        Dimensions=_metric_dimensions(service_name),
        StartTime=start_time,
        EndTime=end_time,
        Period=period,
        Statistics=[stat],
    )
    return _latest_metric_value(response, stat)


def _service_alarms(cloudwatch, service_name: str) -> list[dict]:
    """Return active CloudWatch alarms related to a service."""
    response = cloudwatch.describe_alarms(StateValue="ALARM")
    alarms = []
    dimension_name = _dimension_name()

    for alarm in response.get("MetricAlarms", []):
        dimensions = alarm.get("Dimensions", [])
        matches_dimension = any(
            dimension.get("Name") == dimension_name and dimension.get("Value") == service_name
            for dimension in dimensions
        )
        matches_name = service_name.lower() in alarm.get("AlarmName", "").lower()
        if not (matches_dimension or matches_name):
            continue

        alarms.append(
            {
                "name": alarm.get("AlarmName"),
                "state": alarm.get("StateValue"),
                "reason": alarm.get("StateReason"),
                "metric": alarm.get("MetricName"),
                "namespace": alarm.get("Namespace"),
                "updated_at": alarm.get("StateUpdatedTimestamp"),
            }
        )

    return alarms


def _health_status(
    error_rate_percent: float | None,
    p95_latency_ms: float | None,
    active_alarms: list[dict],
) -> str:
    """Classify service health from metrics and alarms."""
    if active_alarms:
        return "degraded"

    error_threshold = _threshold("MONITORING_ERROR_RATE_THRESHOLD", 1.0)
    latency_threshold = _threshold("MONITORING_LATENCY_THRESHOLD_MS", 500.0)

    if error_rate_percent is not None and error_rate_percent >= error_threshold:
        return "degraded"
    if p95_latency_ms is not None and p95_latency_ms >= latency_threshold:
        return "degraded"
    if error_rate_percent is None and p95_latency_ms is None:
        return "unknown"
    return "healthy"


def _service_health_payload(service_name: str) -> dict:
    """Build service health from CloudWatch metrics and active alarms."""
    cloudwatch = _client("cloudwatch")
    error_metric = _metric_name("MONITORING_ERROR_RATE_METRIC", DEFAULT_ERROR_RATE_METRIC)
    latency_metric = _metric_name("MONITORING_LATENCY_METRIC", DEFAULT_LATENCY_METRIC)
    error_rate_percent = _get_metric_value(cloudwatch, service_name, error_metric, "Average")
    p95_latency_ms = _get_metric_value(cloudwatch, service_name, latency_metric, "Average")
    active_alarms = _service_alarms(cloudwatch, service_name)

    return {
        "service": service_name,
        "status": _health_status(error_rate_percent, p95_latency_ms, active_alarms),
        "error_rate_percent": error_rate_percent,
        "p95_latency_ms": p95_latency_ms,
        "active_alarms": active_alarms,
        "metric_source": {
            "namespace": _metric_namespace(),
            "service_dimension": _dimension_name(),
            "error_rate_metric": error_metric,
            "latency_metric": latency_metric,
        },
        "checked_at": _now().isoformat(),
    }


def _deployment_history_payload(service_name: str, n_recent: int = 5) -> dict:
    """Build recent deployment history from CloudWatch Logs."""
    log_group = os.getenv("DEPLOYMENT_LOG_GROUP", DEFAULT_DEPLOYMENT_LOG_GROUP)
    logs = _client("logs")
    end_time = _now()
    start_time = end_time - timedelta(minutes=1440)
    response = logs.filter_log_events(
        logGroupName=log_group,
        filterPattern=f'"{service_name}"',
        startTime=int(start_time.timestamp() * 1000),
        endTime=int(end_time.timestamp() * 1000),
        limit=max(1, n_recent),
    )
    deployments = [
        {
            "timestamp": datetime.fromtimestamp(event["timestamp"] / 1000, UTC).isoformat(),
            "log_stream": event.get("logStreamName"),
            "message": event.get("message", "").strip(),
        }
        for event in response.get("events", [])
    ]

    return {
        "service": service_name,
        "log_group": log_group,
        "deployments": deployments[: max(0, n_recent)],
    }


@mcp.tool()
async def get_service_health(service_name: str) -> str:
    """Return current health signals for a service.

    Uses CloudWatch metrics for error rate and latency, plus active alarm
    state, to classify the service as healthy, degraded, or unknown.
    """
    try:
        return json.dumps(_service_health_payload(service_name), indent=2, default=_json_default)
    except (BotoCoreError, ClientError, NoCredentialsError, Exception) as exc:
        return _error_response("get_service_health", exc)


@mcp.tool()
async def get_deployment_history(service_name: str, n_recent: int = 5) -> str:
    """Return recent deployment events for a service from CloudWatch Logs."""
    try:
        return json.dumps(_deployment_history_payload(service_name, n_recent), indent=2)
    except (BotoCoreError, ClientError, NoCredentialsError, Exception) as exc:
        return _error_response("get_deployment_history", exc)


@mcp.tool()
async def get_incident_summary(service_name: str) -> str:
    """Return an incident-style summary combining health and deployment context."""
    try:
        health = _service_health_payload(service_name)
        deployments = _deployment_history_payload(service_name)
        health_status = health["status"]
        active_alarms = health["active_alarms"]
        severity = "high" if health_status == "degraded" and active_alarms else "low"

        return json.dumps(
            {
                "service": service_name,
                "severity": severity,
                "summary": _summary_sentence(service_name, health),
                "health": health,
                "deployment_history": deployments,
                "recommended_next_steps": _next_steps(health, deployments),
                "generated_at": _now().isoformat(),
            },
            indent=2,
            default=_json_default,
        )
    except (BotoCoreError, ClientError, NoCredentialsError, Exception) as exc:
        return _error_response("get_incident_summary", exc)


def _summary_sentence(service_name: str, health: dict) -> str:
    """Build a short incident summary from CloudWatch health signals."""
    if health["status"] == "unknown":
        return f"No recent CloudWatch health metrics were found for {service_name}."
    if health["status"] == "degraded":
        return (
            f"{service_name} is degraded with error rate "
            f"{health['error_rate_percent']}% and p95 latency {health['p95_latency_ms']} ms."
        )
    return (
        f"{service_name} is healthy with error rate "
        f"{health['error_rate_percent']}% and p95 latency {health['p95_latency_ms']} ms."
    )


def _next_steps(health: dict, deployments: dict) -> list[str]:
    """Suggest basic operator follow-ups for the current health profile."""
    steps: list[str] = []
    if health["status"] == "degraded":
        steps.extend(
            [
                "Review active CloudWatch alarms and error logs around the start of the alarm window.",
                "Check recent GitHub commits touching the service.",
            ]
        )
    if deployments.get("deployments"):
        steps.append("Compare the incident start time with the most recent deployment event.")
    elif health["status"] == "unknown":
        steps.append("Confirm CloudWatch metrics and deployment log group are configured for this service.")

    if not steps:
        steps.append("Continue normal monitoring.")
    return steps


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        port = int(os.getenv("MONITORING_MCP_PORT", os.getenv("MCP_PORT", "8004")))
        mcp.run(transport="sse", host="0.0.0.0", port=port, show_banner=False)
    else:
        mcp.run(show_banner=False)
