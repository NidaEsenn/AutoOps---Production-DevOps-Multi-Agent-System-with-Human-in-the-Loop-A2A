"""A2A client for discovering and delegating work to peer agents."""

from collections.abc import AsyncIterator
from typing import Any

import httpx


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
        """Yield a single completed task result.

        The PRD includes a streaming endpoint for future SSE support. The
        current server is synchronous, so this method keeps the client API shape
        while yielding the normal delegate result once.
        """
        yield await self.delegate(base_url, task_type, input)

    def _headers(self) -> dict[str, str]:
        """Return optional auth headers."""
        if not self.bearer_token:
            return {}
        return {"Authorization": f"Bearer {self.bearer_token}"}

