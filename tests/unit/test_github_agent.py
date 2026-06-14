import pytest

from autoops.agents.github_agent import (
    _extract_pr_comment,
    _extract_pr_number,
    _is_incident_issue_task,
    _is_issue_write,
    _is_pr_comment_write,
    _needs_code_review_delegation,
    _select_read_tool_and_args,
    _select_read_tool,
    github_node,
    github_write_node,
)
from autoops.state import initial_state


def test_selects_pr_list_for_pr_task() -> None:
    assert _select_read_tool("list open PRs") == "list_open_prs"


def test_selects_repo_status_for_commit_task() -> None:
    assert _select_read_tool("show recent commits") == "get_repo_status"


def test_selects_pr_diff_tool_for_diff_task() -> None:
    assert _select_read_tool_and_args("show diff for PR 42") == ("get_pr_diff", {"pr_number": 42})


@pytest.mark.anyio
async def test_create_issue_sets_pending_approval_without_calling_tool() -> None:
    state = await github_node(initial_state("create issue for documentation follow-up"))

    assert state["pending_approval"] is True
    assert state["approval_details"] is not None
    assert state["approval_details"]["tool"] == "create_issue"
    assert "documentation follow-up" in state["approval_details"]["args"]["body"]
    assert "TODO" not in state["approval_details"]["args"]["body"]


@pytest.mark.anyio
async def test_create_incident_issue_collects_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect_incident_context(task: str) -> dict:
        return {
            "service": "checkout-service",
            "monitoring_summary": '{"severity": "high"}',
            "cloudwatch_error_rate": '{"metric_name": "ErrorRate"}',
            "github_repo_status": '{"recent_commits": []}',
            "code_review_findings": '{"status": "passed"}',
        }

    monkeypatch.setattr("autoops.agents.github_agent._collect_incident_context", fake_collect_incident_context)

    state = await github_node(initial_state("Error rate on checkout-service spiked. Triage and create an incident issue."))

    body = state["approval_details"]["args"]["body"]
    assert state["pending_approval"] is True
    assert "Incident context" in body
    assert "checkout-service" in body
    assert "Monitoring summary" in body
    assert "CloudWatch error-rate data" in body
    assert "GitHub repository context" in body
    assert "Code review findings" in body
    assert "read-only context" in state["agent_outputs"]["github"]


def test_detects_issue_write() -> None:
    assert _is_issue_write("create issue for outage")
    assert not _is_issue_write("list issues")


def test_extracts_pr_number_and_comment() -> None:
    assert _extract_pr_number("add comment to PR #42: Looks good") == 42
    assert _extract_pr_number("pull request 17 needs review") == 17
    assert _extract_pr_number("comment on the PR") == 1
    assert _extract_pr_comment('add comment to PR 42: "Looks good"') == "Looks good"


def test_detects_pr_comment_write() -> None:
    assert _is_pr_comment_write("add comment to PR 42: Looks good")
    assert _is_pr_comment_write("leave review comment on pull request 7")
    assert not _is_pr_comment_write("show comments on PR 42")


@pytest.mark.anyio
async def test_add_pr_comment_sets_pending_approval_without_calling_tool() -> None:
    state = await github_node(initial_state("add comment to PR 42: Looks good after risk review"))

    assert state["pending_approval"] is True
    assert state["approval_details"] == {
        "action": "Add GitHub PR comment to PR #42",
        "tool": "add_pr_comment",
        "args": {
            "pr_number": 42,
            "comment": "Looks good after risk review",
        },
        "agent": "github",
    }


@pytest.mark.anyio
async def test_pr_diff_task_calls_get_pr_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_github_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: {args}"

    monkeypatch.setattr("autoops.agents.github_agent._call_github_tool", fake_call_github_tool)

    state = await github_node(initial_state("show diff for PR 42"))

    assert state["agent_outputs"]["github"] == "get_pr_diff: {'pr_number': 42}"


@pytest.mark.anyio
async def test_github_write_executes_approved_pr_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_github_tool(tool_name: str, args: dict | None = None) -> str:
        return f"{tool_name}: {args}"

    monkeypatch.setattr("autoops.agents.github_agent._call_github_tool", fake_call_github_tool)

    state = initial_state("add comment to PR 42: Looks good")
    state["write_approved"] = True
    state["approval_details"] = {
        "action": "Add GitHub PR comment to PR #42",
        "tool": "add_pr_comment",
        "args": {
            "pr_number": 42,
            "comment": "Looks good",
        },
        "agent": "github",
    }

    final_state = await github_write_node(state)

    assert final_state["pending_approval"] is False
    assert final_state["approval_details"] is None
    assert final_state["agent_outputs"]["github_write"] == (
        "add_pr_comment: {'pr_number': 42, 'comment': 'Looks good'}"
    )


def test_detects_incident_issue_task() -> None:
    assert _is_incident_issue_task("Error rate on checkout-service spiked. Triage and create an incident issue.")
    assert not _is_incident_issue_task("create issue for documentation follow-up")


def test_detects_code_review_delegation() -> None:
    assert _needs_code_review_delegation("review PR diff for risk")
    assert not _needs_code_review_delegation("show diff for PR 42")


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
