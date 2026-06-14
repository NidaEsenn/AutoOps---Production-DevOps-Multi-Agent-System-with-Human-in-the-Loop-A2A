import json
import subprocess
from pathlib import Path

import pytest

from autoops.mcp import mcp_codereview
from autoops.mcp.mcp_codereview import run_linter, run_security_scan


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.mark.anyio
async def test_run_linter_uses_flake8_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/flake8" if name == "flake8" else None

    def fake_run_command(args: list[str], cwd: Path | None = None):
        calls.append(args)
        return completed()

    monkeypatch.setattr(mcp_codereview.shutil, "which", fake_which)
    monkeypatch.setattr(mcp_codereview, "_run_command", fake_run_command)

    payload = json.loads(await run_linter("autoops/supervisor.py"))

    assert payload["tool"] == "flake8"
    assert payload["status"] == "passed"
    assert calls == [["flake8", str(Path.cwd() / "autoops/supervisor.py")]]


@pytest.mark.anyio
async def test_run_linter_falls_back_to_py_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(name: str) -> str | None:
        return None

    def fake_run_command(args: list[str], cwd: Path | None = None):
        return completed()

    monkeypatch.setattr(mcp_codereview.shutil, "which", fake_which)
    monkeypatch.setattr(mcp_codereview, "_run_command", fake_run_command)

    payload = json.loads(await run_linter("autoops/supervisor.py"))

    assert payload["tool"] == "py_compile"
    assert payload["fallback"] == "flake8 not found"
    assert payload["status"] == "passed"


@pytest.mark.anyio
async def test_run_security_scan_includes_bandit_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/bandit" if name == "bandit" else None

    def fake_run_command(args: list[str], cwd: Path | None = None):
        return completed(
            stdout=json.dumps(
                {
                    "results": [
                        {
                            "filename": "autoops/demo.py",
                            "line_number": 10,
                            "test_id": "B101",
                            "issue_severity": "LOW",
                            "issue_confidence": "HIGH",
                            "issue_text": "assert used",
                        }
                    ]
                }
            ),
            returncode=1,
        )

    monkeypatch.setattr(mcp_codereview.shutil, "which", fake_which)
    monkeypatch.setattr(mcp_codereview, "_run_command", fake_run_command)

    payload = json.loads(await run_security_scan("autoops/"))

    assert payload["status"] == "attention_required"
    assert payload["tools"][0]["tool"] == "bandit"
    assert payload["findings"][0]["rule"] == "B101"


@pytest.mark.anyio
async def test_run_security_scan_reports_skipped_bandit_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_codereview.shutil, "which", lambda name: None)

    payload = json.loads(await run_security_scan("autoops/"))

    assert any(tool["tool"] == "bandit" and tool["status"] == "skipped" for tool in payload["tools"])
