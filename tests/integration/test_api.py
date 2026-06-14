import httpx
import pytest

from autoops.api import app


@pytest.mark.anyio
async def test_agents_endpoint_lists_configured_agents() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/agents")

    assert response.status_code == 200
    names = {agent["name"] for agent in response.json()}
    assert names == {"autoops-github", "autoops-cloudwatch", "autoops-codereview", "autoops-monitoring"}


@pytest.mark.anyio
async def test_run_endpoint_completes_ambiguous_task(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "api-checkpoints.db"))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/run", json={"task": "what should I eat today?", "session_id": "api-1"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "complete"
    assert payload["active_agent"] == "end"
    assert "end" in payload["agent_outputs"]


@pytest.mark.anyio
async def test_run_endpoint_returns_approval_required_for_issue(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "api-checkpoints.db"))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/run",
            json={"task": "create issue for documentation follow-up", "session_id": "api-2"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "approval_required"
    assert payload["approval_details"]["tool"] == "create_issue"


@pytest.mark.anyio
async def test_approve_endpoint_can_cancel_without_write(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "api-checkpoints.db"))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/approve", json={"session_id": "api-2", "approved": False})

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "cancelled"
    assert payload["agent_outputs"]["github_write"] == "Cancelled by human reviewer. No GitHub write was executed."
