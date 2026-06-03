import pytest

from autoops.mcp.mcp_monitoring import mcp


@pytest.mark.anyio
async def test_monitoring_mcp_exposes_expected_tools() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert names == {"get_service_health", "get_deployment_history", "get_incident_summary"}

