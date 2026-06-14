import json

import pytest

from autoops.mcp import mcp_github
from autoops.mcp.mcp_github import add_pr_comment, get_pr_diff


@pytest.mark.anyio
async def test_get_pr_diff_calls_gh_pr_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run_gh(args: list[str]) -> str:
        calls.append(args)
        return "diff --git a/app.py b/app.py"

    monkeypatch.setattr(mcp_github, "_run_gh", fake_run_gh)
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    payload = json.loads(await get_pr_diff(42))

    assert calls == [["pr", "diff", "42", "--repo", "owner/repo"]]
    assert payload == {"pr_number": 42, "diff": "diff --git a/app.py b/app.py"}


@pytest.mark.anyio
async def test_add_pr_comment_calls_gh_pr_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run_gh(args: list[str]) -> str:
        calls.append(args)
        return "https://github.com/owner/repo/pull/42#issuecomment-1"

    monkeypatch.setattr(mcp_github, "_run_gh", fake_run_gh)
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    payload = json.loads(await add_pr_comment(42, "Looks good after risk review."))

    assert calls == [
        [
            "pr",
            "comment",
            "42",
            "--body",
            "Looks good after risk review.",
            "--repo",
            "owner/repo",
        ]
    ]
    assert payload == {
        "pr_number": 42,
        "comment_url": "https://github.com/owner/repo/pull/42#issuecomment-1",
    }
