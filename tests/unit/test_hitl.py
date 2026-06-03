import pytest

from autoops.hitl import run_with_approval_loop
from autoops.state import initial_state


@pytest.mark.anyio
async def test_hitl_rejection_does_not_execute_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    async def fail_if_called(tool_name: str, args: dict | None = None) -> str:
        raise AssertionError("write tool should not be called")

    monkeypatch.setattr("autoops.agents.github_agent._call_github_tool", fail_if_called)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.db"))

    final_state = await run_with_approval_loop(initial_state("create issue for checkout incident"))

    assert final_state["pending_approval"] is False
    assert final_state["approval_details"] is None
    assert final_state["agent_outputs"]["github_write"] == "Cancelled by human reviewer. No GitHub write was executed."


@pytest.mark.anyio
async def test_hitl_approval_resumes_and_executes_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    async def fake_call_github_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: approved with {args['title']}"

    monkeypatch.setattr("autoops.agents.github_agent._call_github_tool", fake_call_github_tool)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.db"))

    final_state = await run_with_approval_loop(initial_state("create issue for checkout incident"))

    assert final_state["pending_approval"] is False
    assert final_state["approval_details"] is None
    assert final_state["agent_outputs"]["github_write"] == (
        "create_issue: approved with create issue for checkout incident"
    )
