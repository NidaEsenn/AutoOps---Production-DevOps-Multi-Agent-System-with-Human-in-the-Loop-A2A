import pytest

from autoops.agents.codereview_agent import _extract_path, _select_tool_and_args, codereview_node
from autoops.state import initial_state


def test_extracts_python_file_path() -> None:
    assert _extract_path("run lint on autoops/supervisor.py") == "autoops/supervisor.py"


def test_selects_linter_tool() -> None:
    tool_name, args = _select_tool_and_args("run lint on autoops/supervisor.py")

    assert tool_name == "run_linter"
    assert args == {"file_path": "autoops/supervisor.py"}


def test_selects_security_tool() -> None:
    tool_name, args = _select_tool_and_args("run security scan on autoops/")

    assert tool_name == "run_security_scan"
    assert args == {"repo_path": "autoops/"}


@pytest.mark.anyio
async def test_codereview_node_calls_selected_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_codereview_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: {args}"

    monkeypatch.setattr("autoops.agents.codereview_agent._call_codereview_tool", fake_call_codereview_tool)

    state = await codereview_node(initial_state("run lint on autoops/supervisor.py"))

    assert state["agent_outputs"]["codereview"] == "run_linter: {'file_path': 'autoops/supervisor.py'}"

