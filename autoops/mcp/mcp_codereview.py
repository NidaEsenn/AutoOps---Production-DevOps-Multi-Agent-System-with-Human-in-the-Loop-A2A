"""FastMCP server exposing local code review tools."""

import ast
import json
import os
import shutil
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
    """Run lint checks for a source file.

    Python files use flake8 when available, falling back to py_compile.
    JavaScript and TypeScript files use npm-backed linting when a package
    script exists. Unsupported files return a structured response.
    """
    try:
        path = _safe_path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"file not found: {file_path}")
        if path.suffix == ".py":
            return json.dumps(_run_python_linter(path, file_path), indent=2)
        if path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            return json.dumps(_run_npm_linter(path, file_path), indent=2)

        return json.dumps(
            {
                "file_path": file_path,
                "status": "unsupported",
                "tool": "none",
                "message": "Supported lint targets are Python, JavaScript, and TypeScript files.",
            },
            indent=2,
        )
    except Exception as exc:
        return _error_response("run_linter", exc)


@mcp.tool()
async def run_security_scan(repo_path: str = ".") -> str:
    """Run local security scanning for risky project patterns.

    Python projects use bandit when available, then always include a lightweight
    AST scan for eval(), exec(), shell=True, and possible hardcoded secrets.
    JavaScript projects also run npm audit when package metadata is present.
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

        tool_results = []
        bandit_result = _run_bandit(root, repo_path)
        if bandit_result:
            tool_results.append(bandit_result)
            findings.extend(bandit_result.get("findings", []))

        npm_audit_result = _run_npm_audit(root)
        if npm_audit_result:
            tool_results.append(npm_audit_result)

        return json.dumps(
            {
                "repo_path": repo_path,
                "files_scanned": len(files),
                "tools": tool_results,
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


def _run_command(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a bounded local command and capture output."""
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _run_python_linter(path: Path, file_path: str) -> dict:
    """Run flake8 for Python when available, otherwise py_compile."""
    if shutil.which("flake8"):
        completed = _run_command(["flake8", str(path)])
        return {
            "file_path": file_path,
            "status": "passed" if completed.returncode == 0 else "failed",
            "tool": "flake8",
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }

    completed = _run_command(["python3", "-m", "py_compile", str(path)])
    return {
        "file_path": file_path,
        "status": "passed" if completed.returncode == 0 else "failed",
        "tool": "py_compile",
        "fallback": "flake8 not found",
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _run_npm_linter(path: Path, file_path: str) -> dict:
    """Run npm lint when a package script exists."""
    package_root = _find_parent_with(path, "package.json")
    if not package_root or not shutil.which("npm"):
        return {
            "file_path": file_path,
            "status": "unsupported",
            "tool": "npm",
            "message": "npm or package.json not found.",
        }

    package_json = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    if "lint" not in package_json.get("scripts", {}):
        return {
            "file_path": file_path,
            "status": "unsupported",
            "tool": "npm",
            "message": "package.json has no lint script.",
        }

    completed = _run_command(["npm", "run", "lint", "--", str(path)], cwd=package_root)
    return {
        "file_path": file_path,
        "status": "passed" if completed.returncode == 0 else "failed",
        "tool": "npm lint",
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _run_bandit(root: Path, repo_path: str) -> dict | None:
    """Run bandit if available and return normalized findings."""
    if not shutil.which("bandit"):
        return {
            "tool": "bandit",
            "status": "skipped",
            "reason": "bandit not found",
            "findings": [],
        }

    args = ["bandit", "-f", "json"]
    args.extend(["-r", str(root)] if root.is_dir() else [str(root)])
    completed = _run_command(args)
    try:
        parsed = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        parsed = {}

    findings = [
        {
            "file": result.get("filename"),
            "line": result.get("line_number"),
            "rule": result.get("test_id"),
            "severity": result.get("issue_severity"),
            "confidence": result.get("issue_confidence"),
            "message": result.get("issue_text"),
        }
        for result in parsed.get("results", [])
    ]

    return {
        "tool": "bandit",
        "repo_path": repo_path,
        "status": "passed" if completed.returncode == 0 else "attention_required",
        "findings": findings,
        "stderr": completed.stderr.strip(),
    }


def _run_npm_audit(root: Path) -> dict | None:
    """Run npm audit when package metadata is present."""
    package_root = root if root.is_dir() else root.parent
    package_json = package_root / "package.json"
    if not package_json.exists():
        package_root = _find_parent_with(root, "package.json")
        if not package_root:
            return None

    if not shutil.which("npm"):
        return {"tool": "npm audit", "status": "skipped", "reason": "npm not found"}

    completed = _run_command(["npm", "audit", "--json"], cwd=package_root)
    try:
        parsed = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        parsed = {"raw": completed.stdout.strip()}

    return {
        "tool": "npm audit",
        "status": "passed" if completed.returncode == 0 else "attention_required",
        "summary": parsed.get("metadata", {}).get("vulnerabilities", {}),
        "stderr": completed.stderr.strip(),
    }


def _find_parent_with(path: Path, filename: str) -> Path | None:
    """Find the nearest parent containing a named file within the project root."""
    root = Path.cwd().resolve()
    current = path if path.is_dir() else path.parent
    while root in {current, *current.parents}:
        if (current / filename).exists():
            return current
        if current == root:
            break
        current = current.parent
    return None


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
