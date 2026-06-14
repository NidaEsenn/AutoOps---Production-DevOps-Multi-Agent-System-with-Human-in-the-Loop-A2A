from autoops.mcp.mcp_github import mcp
import pytest


@pytest.mark.anyio
async def test_github_mcp_exposes_expected_tools() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert names == {"list_open_prs", "get_repo_status", "get_pr_diff", "create_issue", "add_pr_comment"}
