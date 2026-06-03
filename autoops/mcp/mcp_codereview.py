"""FastMCP server exposing local code review tools."""

import ast
import json
import os
import subprocess
from pathlib import Path

from fastmcp import FastMCP


mcp = FastMCP("codereview-agent")


SECURITY_PATTERNS = {
    "subprocess_shell_true": "subprocess call with shell=True",
    "hardcoded_secret": "possible hardcoded secret assignment",
    "eval_call": "use of eval()",
    "exec_call": "use of exec()",
}


def _error_response(tool: str, error: Exception) -> str:
    """Return a structured tool error payload."""
    return json.dumps({"tool": tool, "error": str(error)}, indent=2)


def _safe_path(path: str) -> Path:
    """Resolve a path and ensure it stays inside the current project."""
    root = Path.cwd().resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes project root: {path}")
    return resolved


@mcp.tool()
async def run_linter(file_path: str) -> str:
    """Run a lightweight syntax check for a source file.

    Python files are checked with py_compile. Non-Python files return a clear
    unsupported-language response instead of failing unexpectedly.
    """
    try:
        path = _safe_path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"file not found: {file_path}")
        if path.suffix != ".py":
            return json.dumps(
                {
                    "file_path": file_path,
                    "status": "unsupported",
                    "message": "Only Python syntax checks are supported in this first implementation.",
                },
                indent=2,
            )

        completed = subprocess.run(
            ["python3", "-m", "py_compile", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.dumps(
            {
                "file_path": file_path,
                "status": "passed" if completed.returncode == 0 else "failed",
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("run_linter", exc)


@mcp.tool()
async def run_security_scan(repo_path: str = ".") -> str:
    """Run a lightweight local security scan for risky Python patterns.

    This first implementation scans Python ASTs for eval(), exec(), shell=True,
    and possible hardcoded secret assignments.
    """
    try:
        root = _safe_path(repo_path)
        if not root.exists():
            raise FileNotFoundError(f"path not found: {repo_path}")

        files = [root] if root.is_file() else list(root.rglob("*.py"))
        findings: list[dict] = []

        for path in files:
            if any(part.startswith(".") for part in path.relative_to(root if root.is_dir() else path.parent).parts):
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            findings.extend(_scan_tree(path, tree))

        return json.dumps(
            {
                "repo_path": repo_path,
                "files_scanned": len(files),
                "findings": findings,
                "status": "passed" if not findings else "attention_required",
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("run_security_scan", exc)


def _scan_tree(path: Path, tree: ast.AST) -> list[dict]:
    """Scan a Python AST for simple risky patterns."""
    findings: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                findings.append(
                    {
                        "file": str(path),
                        "line": node.lineno,
                        "rule": "eval_call" if node.func.id == "eval" else "exec_call",
                        "message": SECURITY_PATTERNS["eval_call" if node.func.id == "eval" else "exec_call"],
                    }
                )
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    findings.append(
                        {
                            "file": str(path),
                            "line": node.lineno,
                            "rule": "subprocess_shell_true",
                            "message": SECURITY_PATTERNS["subprocess_shell_true"],
                        }
                    )

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _looks_like_secret(target.id) and isinstance(node.value, ast.Constant):
                    findings.append(
                        {
                            "file": str(path),
                            "line": node.lineno,
                            "rule": "hardcoded_secret",
                            "message": SECURITY_PATTERNS["hardcoded_secret"],
                        }
                    )
    return findings


def _looks_like_secret(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in ("secret", "token", "password", "api_key"))


@mcp.tool()
async def get_diff_summary(diff_text: str) -> str:
    """Summarize a git diff and estimate risk level using simple heuristics."""
    try:
        added = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
        touched_files = [line[10:] for line in diff_text.splitlines() if line.startswith("diff --git ")]
        risky_terms = ["password", "secret", "token", "auth", "subprocess", "shell=True", "eval("]
        findings = [term for term in risky_terms if term.lower() in diff_text.lower()]

        if findings or added + removed > 300:
            risk_level = "high"
        elif added + removed > 75:
            risk_level = "medium"
        else:
            risk_level = "low"

        return json.dumps(
            {
                "risk_level": risk_level,
                "files_touched": touched_files,
                "lines_added": added,
                "lines_removed": removed,
                "findings": findings,
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("get_diff_summary", exc)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        port = int(os.getenv("CODEREVIEW_MCP_PORT", os.getenv("MCP_PORT", "8003")))
        mcp.run(transport="sse", host="0.0.0.0", port=port, show_banner=False)
    else:
        mcp.run(show_banner=False)

