"""FastMCP server exposing AWS CloudWatch read tools."""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastmcp import FastMCP


mcp = FastMCP("cloudwatch-agent")


def _error_response(tool: str, error: Exception) -> str:
    """Return a structured tool error payload."""
    return json.dumps(
        {
            "tool": tool,
            "error": str(error),
            "hint": "Check AWS credentials, AWS_DEFAULT_REGION, permissions, and resource names.",
        },
        indent=2,
    )


def _client(service_name: str):
    """Create a boto3 client using the default AWS environment/session."""
    return boto3.client(service_name, region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


def _json_default(value: Any) -> str:
    """Serialize datetimes and other AWS response values to JSON."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@mcp.tool()
async def get_log_events(log_group: str, minutes: int = 30, limit: int = 50) -> str:
    """Return recent CloudWatch log events for a log group.

    This is a read-only operation. It uses filter_log_events over the requested
    recent time window and returns the newest matching events.
    """
    try:
        logs = _client("logs")
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(minutes=minutes)
        response = logs.filter_log_events(
            logGroupName=log_group,
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
            limit=limit,
        )
        events = [
            {
                "timestamp": datetime.fromtimestamp(event["timestamp"] / 1000, UTC).isoformat(),
                "log_stream": event.get("logStreamName"),
                "message": event.get("message", "").strip(),
            }
            for event in response.get("events", [])
        ]
        return json.dumps(
            {
                "log_group": log_group,
                "minutes": minutes,
                "events": events,
            },
            indent=2,
        )
    except (BotoCoreError, ClientError, NoCredentialsError, Exception) as exc:
        return _error_response("get_log_events", exc)


@mcp.tool()
async def list_alarms(state_filter: str = "ALARM") -> str:
    """List CloudWatch metric alarms by state."""
    try:
        cloudwatch = _client("cloudwatch")
        response = cloudwatch.describe_alarms(StateValue=state_filter)
        alarms = [
            {
                "name": alarm.get("AlarmName"),
                "state": alarm.get("StateValue"),
                "reason": alarm.get("StateReason"),
                "metric": alarm.get("MetricName"),
                "namespace": alarm.get("Namespace"),
                "updated_at": alarm.get("StateUpdatedTimestamp"),
            }
            for alarm in response.get("MetricAlarms", [])
        ]
        return json.dumps(
            {
                "state_filter": state_filter,
                "alarms": alarms,
            },
            indent=2,
            default=_json_default,
        )
    except (BotoCoreError, ClientError, NoCredentialsError, Exception) as exc:
        return _error_response("list_alarms", exc)


@mcp.tool()
async def get_metrics(
    namespace: str,
    metric_name: str,
    dimensions: dict[str, str] | None = None,
    minutes: int = 60,
    period: int = 300,
    stat: str = "Average",
) -> str:
    """Return recent CloudWatch metric datapoints.

    Dimensions should be supplied as a JSON object, for example:
    {"ServiceName": "checkout-service"}.
    """
    try:
        cloudwatch = _client("cloudwatch")
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(minutes=minutes)
        response = cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=[
                {"Name": name, "Value": value}
                for name, value in (dimensions or {}).items()
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=[stat],
        )
        datapoints = sorted(response.get("Datapoints", []), key=lambda point: point["Timestamp"])
        return json.dumps(
            {
                "namespace": namespace,
                "metric_name": metric_name,
                "dimensions": dimensions or {},
                "stat": stat,
                "datapoints": datapoints,
            },
            indent=2,
            default=_json_default,
        )
    except (BotoCoreError, ClientError, NoCredentialsError, Exception) as exc:
        return _error_response("get_metrics", exc)


@mcp.tool()
async def describe_recent_deployments(service_name: str, minutes: int = 1440) -> str:
    """Describe recent deployment-like events from CloudWatch logs.

    This first implementation searches the log group named by
    DEPLOYMENT_LOG_GROUP, or /aws/autoops/deployments by default, for the
    service name over the requested window.
    """
    try:
        log_group = os.getenv("DEPLOYMENT_LOG_GROUP", "/aws/autoops/deployments")
        logs = _client("logs")
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(minutes=minutes)
        response = logs.filter_log_events(
            logGroupName=log_group,
            filterPattern=f'"{service_name}"',
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
            limit=25,
        )
        deployments = [
            {
                "timestamp": datetime.fromtimestamp(event["timestamp"] / 1000, UTC).isoformat(),
                "log_stream": event.get("logStreamName"),
                "message": event.get("message", "").strip(),
            }
            for event in response.get("events", [])
        ]
        return json.dumps(
            {
                "service": service_name,
                "log_group": log_group,
                "deployments": deployments,
            },
            indent=2,
        )
    except (BotoCoreError, ClientError, NoCredentialsError, Exception) as exc:
        return _error_response("describe_recent_deployments", exc)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        port = int(os.getenv("CLOUDWATCH_MCP_PORT", os.getenv("MCP_PORT", "8002")))
        mcp.run(transport="sse", host="0.0.0.0", port=port, show_banner=False)
    else:
        mcp.run(show_banner=False)

