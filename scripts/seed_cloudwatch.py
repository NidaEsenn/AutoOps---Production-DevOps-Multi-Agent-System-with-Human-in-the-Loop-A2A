"""Seed CloudWatch with demo data so AutoOps monitoring returns live results.

Pushes an elevated ErrorRate + Latency metric for a service, writes a
deployment log event, and (optionally) creates an alarm — matching the env
defaults the monitoring agent reads (AutoOps/Services namespace, ServiceName
dimension, ErrorRate/Latency metrics, /aws/autoops/deployments log group).

Usage:
    python scripts/seed_cloudwatch.py [service_name]

Requires WRITE permissions: cloudwatch:PutMetricData, cloudwatch:PutMetricAlarm,
logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents.
"""

import os
import sys
import time
from datetime import UTC, datetime

import boto3

REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
NAMESPACE = os.getenv("MONITORING_METRIC_NAMESPACE", "AutoOps/Services")
DIMENSION = os.getenv("MONITORING_SERVICE_DIMENSION", "ServiceName")
ERROR_METRIC = os.getenv("MONITORING_ERROR_RATE_METRIC", "ErrorRate")
LATENCY_METRIC = os.getenv("MONITORING_LATENCY_METRIC", "Latency")
LOG_GROUP = os.getenv("DEPLOYMENT_LOG_GROUP", "/aws/autoops/deployments")


def seed_metrics(service: str) -> None:
    """Push an elevated error rate and latency so the service looks degraded."""
    cw = boto3.client("cloudwatch", region_name=REGION)
    now = datetime.now(UTC)
    dims = [{"Name": DIMENSION, "Value": service}]
    cw.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[
            {"MetricName": ERROR_METRIC, "Dimensions": dims, "Timestamp": now,
             "Value": 5.0, "Unit": "Percent"},
            {"MetricName": LATENCY_METRIC, "Dimensions": dims, "Timestamp": now,
             "Value": 850.0, "Unit": "Milliseconds"},
        ],
    )
    print(f"  metrics  → {ERROR_METRIC}=5.0%, {LATENCY_METRIC}=850ms for {service}")


def seed_alarm(service: str) -> None:
    """Create an ALARM-state alarm tied to the service error rate."""
    cw = boto3.client("cloudwatch", region_name=REGION)
    name = f"{service}-high-error-rate"
    cw.put_metric_alarm(
        AlarmName=name,
        Namespace=NAMESPACE,
        MetricName=ERROR_METRIC,
        Dimensions=[{"Name": DIMENSION, "Value": service}],
        Statistic="Average",
        Period=60,
        EvaluationPeriods=1,
        Threshold=1.0,
        ComparisonOperator="GreaterThanThreshold",
        AlarmDescription=f"Error rate for {service} exceeded 1%",
    )
    # Force the alarm into ALARM state so list_alarms / health pick it up now.
    cw.set_alarm_state(AlarmName=name, StateValue="ALARM",
                       StateReason="Seeded demo incident: error rate spike")
    print(f"  alarm    → {name} forced to ALARM state")


def seed_deployment_log(service: str) -> None:
    """Write a recent deployment event into the deployment log group."""
    logs = boto3.client("logs", region_name=REGION)
    stream = f"deploy-{int(time.time())}"
    try:
        logs.create_log_group(logGroupName=LOG_GROUP)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.create_log_stream(logGroupName=LOG_GROUP, logStreamName=stream)
    logs.put_log_events(
        logGroupName=LOG_GROUP,
        logStreamName=stream,
        logEvents=[{
            "timestamp": int(time.time() * 1000),
            "message": f"Deployed {service} v1.4.2 — commit a1b2c3d (payment retry change)",
        }],
    )
    print(f"  log      → deployment event for {service} in {LOG_GROUP}")


def main() -> None:
    service = sys.argv[1] if len(sys.argv) > 1 else "checkout-service"
    print(f"Seeding CloudWatch demo data for '{service}' in {REGION}...")
    seed_metrics(service)
    seed_alarm(service)
    seed_deployment_log(service)
    print("Done. Try: python -m autoops.main \"show health for "
          f"{service}\"")


if __name__ == "__main__":
    main()
