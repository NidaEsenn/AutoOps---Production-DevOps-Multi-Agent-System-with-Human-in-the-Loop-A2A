"""FastMCP server exposing GitHub CLI tools."""

import json
import os
import subprocess
from typing import Any

from fastmcp import FastMCP


mcp = FastMCP("github-agent")


class GitHubCliError(RuntimeError):
    """Raised when the GitHub CLI returns a failing exit code."""


def _run_gh(args: list[str]) -> str:
    """Run a GitHub CLI command and return stdout."""
    completed = subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise GitHubCliError(message or f"gh exited with code {completed.returncode}")

    return completed.stdout.strip()


def _json_or_text(output: str) -> Any:
    """Parse GitHub CLI JSON output when possible."""
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output


def _error_response(tool: str, error: Exception) -> str:
    """Return a structured tool error payload."""
    return json.dumps(
        {
            "tool": tool,
            "error": str(error),
        },
        indent=2,
    )


@mcp.tool()
async def list_open_prs() -> str:
    """List open pull requests for the current or configured GitHub repository.

    This is a read-only operation and does not require human approval.
    """
    repo = os.getenv("GITHUB_REPO")
    args = [
        "pr",
        "list",
        "--state",
        "open",
        "--json",
        "number,title,author,headRefName,baseRefName,url,updatedAt",
    ]
    if repo:
        args.extend(["--repo", repo])

    try:
        result = _json_or_text(_run_gh(args))
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response("list_open_prs", exc)


@mcp.tool()
async def get_repo_status() -> str:
    """Return recent repository status from the GitHub CLI.

    Includes repository metadata and recent commits for the current branch. This
    is a read-only operation and does not require human approval.
    """
    repo = os.getenv("GITHUB_REPO")

    repo_args = ["repo", "view", "--json", "nameWithOwner,description,url,defaultBranchRef"]
    commit_args = ["api", "repos/{owner}/{repo}/commits", "--paginate", "-F", "per_page=5"]

    if repo:
        repo_args.extend(["--repo", repo])
        owner, repo_name = repo.split("/", maxsplit=1)
        commit_args = [
            "api",
            f"repos/{owner}/{repo_name}/commits",
            "-F",
            "per_page=5",
        ]

    try:
        repo_info = _json_or_text(_run_gh(repo_args))
        commits = _json_or_text(_run_gh(commit_args))
    except Exception as exc:
        return _error_response("get_repo_status", exc)

    return json.dumps(
        {
            "repository": repo_info,
            "recent_commits": commits,
        },
        indent=2,
    )


@mcp.tool()
async def get_pr_diff(pr_number: int) -> str:
    """Return the diff for a pull request.

    This is a read-only operation and does not require human approval.
    """
    repo = os.getenv("GITHUB_REPO")
    args = ["pr", "diff", str(pr_number)]

    if repo:
        args.extend(["--repo", repo])

    try:
        diff = _run_gh(args)
        return json.dumps(
            {
                "pr_number": pr_number,
                "diff": diff,
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("get_pr_diff", exc)


@mcp.tool()
async def create_issue(title: str, body: str, labels: list[str] | None = None) -> str:
    """Create a GitHub issue in the current or configured repository.

    This is a write operation. AutoOps must request human approval before an
    agent calls this tool.
    """
    repo = os.getenv("GITHUB_REPO")
    args = ["issue", "create", "--title", title, "--body", body]

    if repo:
        args.extend(["--repo", repo])

    for label in labels or []:
        args.extend(["--label", label])

    try:
        url = _run_gh(args)
        return json.dumps({"issue_url": url}, indent=2)
    except Exception as exc:
        return _error_response("create_issue", exc)


@mcp.tool()
async def add_pr_comment(pr_number: int, comment: str) -> str:
    """Add a comment to a pull request.

    This is a write operation. AutoOps must request human approval before an
    agent calls this tool.
    """
    repo = os.getenv("GITHUB_REPO")
    args = ["pr", "comment", str(pr_number), "--body", comment]

    if repo:
        args.extend(["--repo", repo])

    try:
        output = _run_gh(args)
        return json.dumps(
            {
                "pr_number": pr_number,
                "comment_url": output,
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("add_pr_comment", exc)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        port = int(os.getenv("GITHUB_MCP_PORT", os.getenv("MCP_PORT", "8001")))
        mcp.run(transport="sse", host="0.0.0.0", port=port, show_banner=False)
    else:
        mcp.run(show_banner=False)
