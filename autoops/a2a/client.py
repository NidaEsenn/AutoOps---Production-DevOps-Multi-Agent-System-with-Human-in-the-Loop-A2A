"""A2A client for discovering and delegating work to peer agents."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from autoops.observability import tool_span


class A2AClient:
    """Small async HTTP client for the AutoOps A2A protocol."""

    def __init__(self, bearer_token: str | None = None, timeout: float = 15.0) -> None:
        self.bearer_token = bearer_token
        self.timeout = timeout

    async def discover(self, base_url: str) -> dict:
        """Fetch an Agent Card from /.well-known/agent.json."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{base_url.rstrip('/')}/.well-known/agent.json")
            response.raise_for_status()
            return response.json()

    async def delegate(self, base_url: str, task_type: str, input: dict) -> dict:
        """POST an A2A task and return the completed task payload."""
        headers = self._headers()
        payload = {"type": task_type, "input": input}

        with tool_span("a2a.delegate", agent="a2a", target_agent=base_url, task_type=task_type):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/tasks",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                result: dict[str, Any] = response.json()

        if result.get("status") == "failed":
            raise RuntimeError(result.get("error") or "A2A task failed")
        return result

    async def stream_delegate(self, base_url: str, task_type: str, input: dict) -> AsyncIterator[dict]:
        """POST an A2A task and yield SSE lifecycle events."""
        headers = self._headers()
        payload = {"type": task_type, "input": input}

        with tool_span("a2a.stream_delegate", agent="a2a", target_agent=base_url, task_type=task_type):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{base_url.rstrip('/')}/tasks/stream",
                    json=payload,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    event_type: str | None = None
                    data_lines: list[str] = []

                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            event_type = line.removeprefix("event:").strip()
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line.removeprefix("data:").strip())
                            continue
                        if line == "" and data_lines:
                            payload_data = json_loads("\n".join(data_lines))
                            if event_type:
                                payload_data["event"] = event_type
                            yield payload_data
                            event_type = None
                            data_lines = []

    def _headers(self) -> dict[str, str]:
        """Return optional auth headers."""
        if not self.bearer_token:
            return {}
        return {"Authorization": f"Bearer {self.bearer_token}"}


def json_loads(value: str) -> dict:
    """Parse a JSON object for streamed A2A events."""
    import json

    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {"result": parsed}
