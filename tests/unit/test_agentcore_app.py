"""Tests for the AgentCore entrypoint wrapper."""

import pytest

from autoops.agentcore_app import invoke


@pytest.mark.anyio
async def test_entrypoint_rejects_missing_task() -> None:
    result = await invoke({})

    assert result["status"] == "failed"
    assert "task" in result["error"].lower()


@pytest.mark.anyio
async def test_entrypoint_runs_read_only_task(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_github_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: real MCP call mocked for unit test"

    monkeypatch.setattr("autoops.agents.github_agent._call_github_tool", fake_call_github_tool)

    result = await invoke({"task": "list open PRs", "session_id": "test-ro"})

    assert result["status"] == "complete"
    assert "supervisor" in result["agent_outputs"]
    assert "github" in result["agent_outputs"]


@pytest.mark.anyio
async def test_entrypoint_pauses_for_write_approval() -> None:
    # The write path sets pending_approval and returns before any tool runs,
    # so no GitHub call is made here.
    result = await invoke(
        {"task": "create an issue for the checkout-service outage", "session_id": "test-write"}
    )

    assert result["status"] == "approval_required"
    assert result["approval_details"]["tool"] == "create_issue"
