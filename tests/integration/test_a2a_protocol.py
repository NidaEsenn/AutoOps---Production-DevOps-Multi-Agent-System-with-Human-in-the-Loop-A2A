import httpx
import pytest

from autoops.a2a.client import A2AClient
from autoops.a2a.models import A2ATask
from autoops.a2a.server import app


def test_a2a_task_defaults_to_submitted() -> None:
    task = A2ATask(type="diff_summary", input={"diff_text": "example"})

    assert task.status == "submitted"
    assert task.id


@pytest.mark.anyio
async def test_agent_card_endpoint() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/.well-known/agent.json")

    assert response.status_code == 200
    assert response.json()["name"] == "autoops-codereview"
    assert "diff_summary" in response.json()["capabilities"]["tasks"]


@pytest.mark.anyio
async def test_task_endpoint_completes_diff_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_codereview_tool(tool_name: str, args: dict | None = None) -> str:
        return '{"risk_level": "low", "findings": []}'

    monkeypatch.setattr("autoops.a2a.server._call_codereview_tool", fake_call_codereview_tool)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/tasks", json={"type": "diff_summary", "input": {"diff_text": "diff"}})

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "completed"
    assert payload["output"] == {"risk_level": "low", "findings": []}


@pytest.mark.anyio
async def test_stream_task_endpoint_emits_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_codereview_tool(tool_name: str, args: dict | None = None) -> str:
        return '{"risk_level": "low", "findings": []}'

    monkeypatch.setattr("autoops.a2a.server._call_codereview_tool", fake_call_codereview_tool)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/tasks/stream", json={"type": "diff_summary", "input": {"diff_text": "diff"}})

    assert response.status_code == 200
    assert "event: submitted" in response.text
    assert "event: working" in response.text
    assert "event: completed" in response.text


@pytest.mark.anyio
async def test_a2a_client_delegate_with_mock_transport() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tasks":
            return httpx.Response(
                200,
                json={
                    "id": "task-1",
                    "type": "diff_summary",
                    "input": {"diff_text": "diff"},
                    "status": "completed",
                    "output": {"risk_level": "low"},
                    "error": None,
                    "created_at": "2026-06-01T00:00:00+00:00",
                    "updated_at": "2026-06-01T00:00:00+00:00",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    httpx.AsyncClient = patched_async_client
    try:
        result = await A2AClient().delegate("http://testserver", "diff_summary", {"diff_text": "diff"})
    finally:
        httpx.AsyncClient = original_async_client

    assert result["status"] == "completed"
    assert result["output"] == {"risk_level": "low"}


@pytest.mark.anyio
async def test_a2a_client_stream_delegate_with_mock_transport() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tasks/stream":
            return httpx.Response(
                200,
                text=(
                    'event: submitted\n'
                    'data: {"id": "task-1", "status": "submitted"}\n\n'
                    'event: working\n'
                    'data: {"id": "task-1", "status": "working"}\n\n'
                    'event: completed\n'
                    'data: {"id": "task-1", "status": "completed", "output": {"risk_level": "low"}}\n\n'
                ),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    httpx.AsyncClient = patched_async_client
    try:
        events = [
            event
            async for event in A2AClient().stream_delegate("http://testserver", "diff_summary", {"diff_text": "diff"})
        ]
    finally:
        httpx.AsyncClient = original_async_client

    assert [event["event"] for event in events] == ["submitted", "working", "completed"]
    assert events[-1]["output"] == {"risk_level": "low"}
