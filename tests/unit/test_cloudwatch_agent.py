import pytest

from autoops.agents.cloudwatch_agent import _extract_log_group, _extract_service_name, _select_tool_and_args, cloudwatch_node
from autoops.state import initial_state


def test_extracts_service_name() -> None:
    assert _extract_service_name("error rate for checkout-service") == "checkout-service"


def test_extracts_log_group() -> None:
    assert _extract_log_group("show logs in /aws/lambda/demo", "checkout-service") == "/aws/lambda/demo"


def test_infers_log_group() -> None:
    assert _extract_log_group("show logs for checkout-service", "checkout-service") == "/aws/autoops/checkout-service"


def test_selects_logs_tool() -> None:
    tool_name, args = _select_tool_and_args("show logs for checkout-service")

    assert tool_name == "get_log_events"
    assert args == {"log_group": "/aws/autoops/checkout-service"}


def test_selects_alarms_tool() -> None:
    tool_name, args = _select_tool_and_args("list alarms")

    assert tool_name == "list_alarms"
    assert args == {"state_filter": "ALARM"}


def test_selects_latency_metric_tool() -> None:
    tool_name, args = _select_tool_and_args("latency for checkout-service")

    assert tool_name == "get_metrics"
    assert args["metric_name"] == "Latency"
    assert args["dimensions"] == {"ServiceName": "checkout-service"}


def test_selects_error_rate_metric_tool() -> None:
    tool_name, args = _select_tool_and_args("error rate for checkout-service")

    assert tool_name == "get_metrics"
    assert args["metric_name"] == "ErrorRate"


def test_selects_deployment_tool() -> None:
    tool_name, args = _select_tool_and_args("recent deployments for checkout-service")

    assert tool_name == "describe_recent_deployments"
    assert args == {"service_name": "checkout-service"}


@pytest.mark.anyio
async def test_cloudwatch_node_calls_selected_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_cloudwatch_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: {args}"

    monkeypatch.setattr("autoops.agents.cloudwatch_agent._call_cloudwatch_tool", fake_call_cloudwatch_tool)

    state = await cloudwatch_node(initial_state("list alarms"))

    assert state["agent_outputs"]["cloudwatch"] == "list_alarms: {'state_filter': 'ALARM'}"

