import pytest

from autoops.state import initial_state
from autoops.supervisor import run_graph


@pytest.mark.anyio
async def test_graph_routes_to_github_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_github_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: real MCP call mocked for unit test"

    monkeypatch.setattr("autoops.agents.github_agent._call_github_tool", fake_call_github_tool)

    final_state = await run_graph(initial_state("list open PRs"))

    assert final_state["active_agent"] == "end"
    assert "supervisor" in final_state["agent_outputs"]
    assert final_state["agent_outputs"]["github"] == "list_open_prs: real MCP call mocked for unit test"


@pytest.mark.anyio
async def test_graph_handles_ambiguous_task_without_agent_guessing() -> None:
    final_state = await run_graph(initial_state("what should I eat today?"))

    assert final_state["active_agent"] == "end"
    assert "end" in final_state["agent_outputs"]
    assert "github" not in final_state["agent_outputs"]
    assert "cloudwatch" not in final_state["agent_outputs"]


@pytest.mark.anyio
async def test_graph_routes_to_codereview_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_codereview_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: real MCP call mocked for unit test"

    monkeypatch.setattr("autoops.agents.codereview_agent._call_codereview_tool", fake_call_codereview_tool)

    final_state = await run_graph(initial_state("run lint on autoops/supervisor.py"))

    assert final_state["active_agent"] == "end"
    assert final_state["agent_outputs"]["codereview"] == "run_linter: real MCP call mocked for unit test"


@pytest.mark.anyio
async def test_graph_routes_to_monitoring_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_monitoring_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: real MCP call mocked for unit test"

    monkeypatch.setattr("autoops.agents.monitoring_agent._call_monitoring_tool", fake_call_monitoring_tool)

    final_state = await run_graph(initial_state("show health for checkout-service"))

    assert final_state["active_agent"] == "end"
    assert final_state["agent_outputs"]["monitoring"] == "get_service_health: real MCP call mocked for unit test"


@pytest.mark.anyio
async def test_graph_routes_to_cloudwatch_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_cloudwatch_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: real MCP call mocked for unit test"

    monkeypatch.setattr("autoops.agents.cloudwatch_agent._call_cloudwatch_tool", fake_call_cloudwatch_tool)

    final_state = await run_graph(initial_state("error rate for checkout-service"))

    assert final_state["active_agent"] == "end"
    assert final_state["agent_outputs"]["cloudwatch"] == "get_metrics: real MCP call mocked for unit test"
