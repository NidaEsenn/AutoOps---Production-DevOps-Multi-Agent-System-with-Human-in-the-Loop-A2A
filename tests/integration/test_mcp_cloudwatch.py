import pytest

from autoops.mcp.mcp_cloudwatch import mcp


@pytest.mark.anyio
async def test_cloudwatch_mcp_exposes_expected_tools() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert names == {"get_log_events", "list_alarms", "get_metrics", "describe_recent_deployments"}

