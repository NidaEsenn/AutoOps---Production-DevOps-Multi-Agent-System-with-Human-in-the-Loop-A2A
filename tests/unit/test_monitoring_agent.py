import pytest

from autoops.agents.monitoring_agent import _extract_service_name, _select_tool_and_args, monitoring_node
from autoops.state import initial_state


def test_extracts_service_name() -> None:
    assert _extract_service_name("show health for payments-service") == "payments-service"


def test_defaults_service_name() -> None:
    assert _extract_service_name("show service health") == "checkout-service"


def test_selects_health_tool() -> None:
    tool_name, args = _select_tool_and_args("show health for checkout-service")

    assert tool_name == "get_service_health"
    assert args == {"service_name": "checkout-service"}


def test_selects_deployment_history_tool() -> None:
    tool_name, args = _select_tool_and_args("show deployment history for checkout-service")

    assert tool_name == "get_deployment_history"
    assert args == {"service_name": "checkout-service"}


def test_selects_incident_summary_tool() -> None:
    tool_name, args = _select_tool_and_args("incident summary for checkout-service")

    assert tool_name == "get_incident_summary"
    assert args == {"service_name": "checkout-service"}


@pytest.mark.anyio
async def test_monitoring_node_calls_selected_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_monitoring_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: {args}"

    monkeypatch.setattr("autoops.agents.monitoring_agent._call_monitoring_tool", fake_call_monitoring_tool)

    state = await monitoring_node(initial_state("show health for checkout-service"))

    assert state["agent_outputs"]["monitoring"] == "get_service_health: {'service_name': 'checkout-service'}"

