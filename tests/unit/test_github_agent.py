import pytest

from autoops.agents.github_agent import _is_issue_write, _needs_code_review_delegation, _select_read_tool, github_node
from autoops.state import initial_state


def test_selects_pr_list_for_pr_task() -> None:
    assert _select_read_tool("list open PRs") == "list_open_prs"


def test_selects_repo_status_for_commit_task() -> None:
    assert _select_read_tool("show recent commits") == "get_repo_status"


@pytest.mark.anyio
async def test_create_issue_sets_pending_approval_without_calling_tool() -> None:
    state = await github_node(initial_state("create issue for checkout incident"))

    assert state["pending_approval"] is True
    assert state["approval_details"] is not None
    assert state["approval_details"]["tool"] == "create_issue"


def test_detects_issue_write() -> None:
    assert _is_issue_write("create issue for outage")
    assert not _is_issue_write("list issues")


def test_detects_code_review_delegation() -> None:
    assert _needs_code_review_delegation("review PR diff for risk")
    assert not _needs_code_review_delegation("list open PRs")


@pytest.mark.anyio
async def test_pr_analysis_delegates_to_codereview(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delegate_pr_analysis(task: str) -> dict:
        return {
            "id": "task-1",
            "status": "completed",
            "output": {"risk_level": "low"},
        }

    monkeypatch.setattr("autoops.agents.github_agent._delegate_pr_analysis", fake_delegate_pr_analysis)

    state = await github_node(initial_state("review PR diff for risk"))

    assert state["a2a_delegations"] == [
        {
            "target_agent": "autoops-codereview",
            "task_type": "diff_summary",
            "status": "completed",
            "task_id": "task-1",
        }
    ]
    assert "Delegated PR analysis" in state["agent_outputs"]["github"]


@pytest.mark.anyio
async def test_pr_analysis_delegation_failure_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delegate_pr_analysis(task: str) -> dict:
        raise RuntimeError("server down")

    monkeypatch.setattr("autoops.agents.github_agent._delegate_pr_analysis", fake_delegate_pr_analysis)

    state = await github_node(initial_state("review PR diff for risk"))

    assert state["a2a_delegations"][0]["status"] == "failed"
    assert "continuing with warning" in state["agent_outputs"]["github"]
