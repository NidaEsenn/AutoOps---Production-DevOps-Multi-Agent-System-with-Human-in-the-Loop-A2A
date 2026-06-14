import json
from datetime import UTC, datetime

import pytest

from autoops.mcp import mcp_monitoring
from autoops.mcp.mcp_monitoring import get_deployment_history, get_incident_summary, get_service_health


class FakeCloudWatchClient:
    def get_metric_statistics(self, **kwargs):
        metric_name = kwargs["MetricName"]
        value = 3.2 if metric_name == "ErrorRate" else 640.0
        return {
            "Datapoints": [
                {
                    "Timestamp": datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                    "Average": value,
                }
            ]
        }

    def describe_alarms(self, **kwargs):
        return {
            "MetricAlarms": [
                {
                    "AlarmName": "CheckoutHighErrorRate",
                    "StateValue": "ALARM",
                    "StateReason": "Threshold crossed",
                    "MetricName": "ErrorRate",
                    "Namespace": "AutoOps/Services",
                    "Dimensions": [{"Name": "ServiceName", "Value": "checkout-service"}],
                    "StateUpdatedTimestamp": datetime(2026, 6, 1, 12, 5, tzinfo=UTC),
                },
                {
                    "AlarmName": "InventoryHighLatency",
                    "StateValue": "ALARM",
                    "StateReason": "Threshold crossed",
                    "MetricName": "Latency",
                    "Namespace": "AutoOps/Services",
                    "Dimensions": [{"Name": "ServiceName", "Value": "inventory-service"}],
                    "StateUpdatedTimestamp": datetime(2026, 6, 1, 12, 5, tzinfo=UTC),
                },
            ]
        }


class FakeLogsClient:
    def filter_log_events(self, **kwargs):
        return {
            "events": [
                {
                    "timestamp": 1780315500000,
                    "logStreamName": "deployments/checkout-service",
                    "message": "checkout-service deployed version 2026.06.01 to production",
                }
            ]
        }


class FakeHealthyCloudWatchClient(FakeCloudWatchClient):
    def get_metric_statistics(self, **kwargs):
        metric_name = kwargs["MetricName"]
        value = 0.2 if metric_name == "ErrorRate" else 180.0
        return {
            "Datapoints": [
                {
                    "Timestamp": datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                    "Average": value,
                }
            ]
        }

    def describe_alarms(self, **kwargs):
        return {"MetricAlarms": []}


def patch_clients(monkeypatch: pytest.MonkeyPatch, cloudwatch=None, logs=None) -> None:
    cloudwatch = cloudwatch or FakeCloudWatchClient()
    logs = logs or FakeLogsClient()

    def fake_client(service_name: str):
        if service_name == "cloudwatch":
            return cloudwatch
        if service_name == "logs":
            return logs
        raise AssertionError(f"unexpected service: {service_name}")

    monkeypatch.setattr(mcp_monitoring, "_client", fake_client)


@pytest.mark.anyio
async def test_get_service_health_uses_cloudwatch_metrics_and_alarms(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_clients(monkeypatch)

    payload = json.loads(await get_service_health("checkout-service"))

    assert payload["service"] == "checkout-service"
    assert payload["status"] == "degraded"
    assert payload["error_rate_percent"] == 3.2
    assert payload["p95_latency_ms"] == 640.0
    assert payload["active_alarms"][0]["name"] == "CheckoutHighErrorRate"
    assert payload["metric_source"]["namespace"] == "AutoOps/Services"


@pytest.mark.anyio
async def test_get_service_health_marks_healthy_when_metrics_under_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_clients(monkeypatch, cloudwatch=FakeHealthyCloudWatchClient())

    payload = json.loads(await get_service_health("payments-service"))

    assert payload["status"] == "healthy"
    assert payload["active_alarms"] == []


@pytest.mark.anyio
async def test_get_deployment_history_reads_cloudwatch_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_clients(monkeypatch)

    payload = json.loads(await get_deployment_history("checkout-service"))

    assert payload["service"] == "checkout-service"
    assert payload["log_group"] == "/aws/autoops/deployments"
    assert payload["deployments"][0]["message"] == "checkout-service deployed version 2026.06.01 to production"


@pytest.mark.anyio
async def test_get_incident_summary_combines_health_and_deployment_history(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_clients(monkeypatch)

    payload = json.loads(await get_incident_summary("checkout-service"))

    assert payload["severity"] == "high"
    assert payload["health"]["status"] == "degraded"
    assert payload["deployment_history"]["deployments"]
    assert "checkout-service is degraded" in payload["summary"]
    assert "Compare the incident start time" in payload["recommended_next_steps"][-1]
