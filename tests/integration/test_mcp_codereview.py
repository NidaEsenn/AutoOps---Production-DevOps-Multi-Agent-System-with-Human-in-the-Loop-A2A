import pytest

from autoops.mcp.mcp_codereview import mcp


@pytest.mark.anyio
async def test_codereview_mcp_exposes_expected_tools() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert names == {"run_linter", "run_security_scan", "get_diff_summary"}

