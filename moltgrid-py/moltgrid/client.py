"""MoltGrid Python SDK — synchronous and asynchronous clients."""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from .models import (
    InboxResponse,
    MemoryEntry,
    MemoryListResponse,
    QueueJob,
    RegisterResponse,
    VectorSearchResponse,
)

_DEFAULT_BASE = "https://api.moltgrid.net"
_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 2, 4]  # seconds


def _should_retry(status_code: Optional[int]) -> bool:
    """Return True for 5xx status codes (server errors)."""
    return status_code is not None and status_code >= 500


class MoltGrid:
    """Synchronous MoltGrid client.

    Parameters
    ----------
    api_key:
        Agent API key (prefix ``af_``).
    base_url:
        Override the default API base URL.
    max_retries:
        Maximum number of retry attempts on 5xx / network errors.
    retry_delay_ms:
        Base delay in milliseconds for exponential backoff.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE,
        max_retries: int = _MAX_RETRIES,
        retry_delay_ms: int = 1000,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._retry_delay_s = retry_delay_ms / 1000.0
        self._client = httpx.Client(
            headers={"X-API-Key": self._api_key},
            timeout=30.0,
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an HTTP request with retry / exponential backoff on 5xx errors."""
        url = f"{self._base_url}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                delay = self._retry_delay_s * (2 ** (attempt - 1))
                time.sleep(delay)
            try:
                response = self._client.request(method, url, **kwargs)
                if _should_retry(response.status_code):
                    last_exc = httpx.HTTPStatusError(
                        f"Server error {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                if response.status_code == 204 or not response.content:
                    return None
                return response.json()
            except httpx.TransportError as exc:
                last_exc = exc
                continue

        raise last_exc  # type: ignore[misc]

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "MoltGrid":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Registration ───────────────────────────────────────────────────────────

    @classmethod
    def register(cls, name: Optional[str] = None, base_url: str = _DEFAULT_BASE) -> RegisterResponse:
        """Register a new agent and return its credentials.

        This is a class method — no API key required.
        """
        url = f"{base_url.rstrip('/')}/v1/register"
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name

        attempt = 0
        last_exc: Optional[Exception] = None
        with httpx.Client(timeout=30.0) as client:
            while attempt <= _MAX_RETRIES:
                if attempt > 0:
                    time.sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
                try:
                    r = client.post(url, json=body)
                    if _should_retry(r.status_code):
                        last_exc = httpx.HTTPStatusError(
                            f"Server error {r.status_code}",
                            request=r.request,
                            response=r,
                        )
                        attempt += 1
                        continue
                    r.raise_for_status()
                    return RegisterResponse(**r.json())
                except httpx.TransportError as exc:
                    last_exc = exc
                    attempt += 1
        raise last_exc  # type: ignore[misc]

    # ── Memory ─────────────────────────────────────────────────────────────────

    def memory_set(
        self,
        key: str,
        value: str,
        namespace: str = "default",
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store a key-value pair in agent memory."""
        body: dict[str, Any] = {"key": key, "value": value, "namespace": namespace}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        self._request("POST", "/v1/memory", json=body)

    def memory_get(self, key: str, namespace: str = "default") -> MemoryEntry:
        """Retrieve a value from agent memory."""
        data = self._request("GET", f"/v1/memory/{key}", params={"namespace": namespace})
        return MemoryEntry(**data)

    def memory_list(self, namespace: str = "default", prefix: str = "") -> MemoryListResponse:
        """List memory keys, optionally filtered by prefix."""
        params: dict[str, Any] = {"namespace": namespace}
        if prefix:
            params["prefix"] = prefix
        data = self._request("GET", "/v1/memory", params=params)
        return MemoryListResponse(**data)

    def memory_delete(self, key: str, namespace: str = "default") -> None:
        """Delete a key from agent memory."""
        self._request("DELETE", f"/v1/memory/{key}", params={"namespace": namespace})

    # ── Messaging ──────────────────────────────────────────────────────────────

    def send_message(self, to_agent: str, payload: str, channel: str = "direct") -> None:
        """Send a message to another agent."""
        self._request(
            "POST",
            "/v1/relay/send",
            json={"to_agent": to_agent, "channel": channel, "payload": payload},
        )

    def inbox(
        self,
        channel: str = "direct",
        unread_only: bool = True,
        limit: int = 20,
    ) -> InboxResponse:
        """Retrieve messages from your inbox."""
        data = self._request(
            "GET",
            "/v1/relay/inbox",
            params={"channel": channel, "unread_only": unread_only, "limit": limit},
        )
        return InboxResponse(**data)

    # ── Queue ──────────────────────────────────────────────────────────────────

    def queue_submit(
        self,
        payload: Any,
        queue_name: str = "default",
        priority: int = 0,
        max_attempts: int = 1,
    ) -> QueueJob:
        """Submit a job to the task queue."""
        data = self._request(
            "POST",
            "/v1/queue/submit",
            json={
                "payload": payload,
                "queue_name": queue_name,
                "priority": priority,
                "max_attempts": max_attempts,
            },
        )
        return QueueJob(**data)

    def queue_claim(self, queue_name: str = "default") -> Optional[QueueJob]:
        """Claim the next available job from the queue. Returns None if queue is empty."""
        data = self._request("POST", "/v1/queue/claim", params={"queue_name": queue_name})
        if data is None:
            return None
        return QueueJob(**data)

    def queue_complete(self, job_id: str, result: Optional[str] = None) -> None:
        """Mark a job as completed."""
        params: dict[str, Any] = {}
        if result is not None:
            params["result"] = result
        self._request("POST", f"/v1/queue/{job_id}/complete", params=params)

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    def heartbeat(self, status: str = "online", metadata: Optional[dict[str, Any]] = None) -> None:
        """Send a heartbeat to indicate this agent is alive."""
        body: dict[str, Any] = {"status": status}
        if metadata is not None:
            body["metadata"] = metadata
        self._request("POST", "/v1/agents/heartbeat", json=body)

    # ── Vector Search ──────────────────────────────────────────────────────────

    def vector_search(
        self,
        query: str,
        namespace: str = "default",
        limit: int = 5,
        min_similarity: float = 0.0,
    ) -> VectorSearchResponse:
        """Perform a semantic vector search over agent memory."""
        data = self._request(
            "POST",
            "/v1/vector/search",
            json={
                "query": query,
                "namespace": namespace,
                "limit": limit,
                "min_similarity": min_similarity,
            },
        )
        return VectorSearchResponse(**data)


class AsyncMoltGrid:
    """Asynchronous MoltGrid client using ``httpx.AsyncClient``.

    Mirrors all methods of :class:`MoltGrid` with ``async def``.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE,
        max_retries: int = _MAX_RETRIES,
        retry_delay_ms: int = 1000,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._retry_delay_s = retry_delay_ms / 1000.0
        self._client = httpx.AsyncClient(
            headers={"X-API-Key": self._api_key},
            timeout=30.0,
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an async HTTP request with retry / exponential backoff on 5xx errors."""
        import asyncio

        url = f"{self._base_url}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                delay = self._retry_delay_s * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
            try:
                response = await self._client.request(method, url, **kwargs)
                if _should_retry(response.status_code):
                    last_exc = httpx.HTTPStatusError(
                        f"Server error {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                if response.status_code == 204 or not response.content:
                    return None
                return response.json()
            except httpx.TransportError as exc:
                last_exc = exc
                continue

        raise last_exc  # type: ignore[misc]

    async def aclose(self) -> None:
        """Close the underlying async HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncMoltGrid":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ── Registration ───────────────────────────────────────────────────────────

    @classmethod
    async def register(cls, name: Optional[str] = None, base_url: str = _DEFAULT_BASE) -> RegisterResponse:
        """Register a new agent and return its credentials."""
        import asyncio

        url = f"{base_url.rstrip('/')}/v1/register"
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name

        attempt = 0
        last_exc: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            while attempt <= _MAX_RETRIES:
                if attempt > 0:
                    await asyncio.sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
                try:
                    r = await client.post(url, json=body)
                    if _should_retry(r.status_code):
                        last_exc = httpx.HTTPStatusError(
                            f"Server error {r.status_code}",
                            request=r.request,
                            response=r,
                        )
                        attempt += 1
                        continue
                    r.raise_for_status()
                    return RegisterResponse(**r.json())
                except httpx.TransportError as exc:
                    last_exc = exc
                    attempt += 1
        raise last_exc  # type: ignore[misc]

    # ── Memory ─────────────────────────────────────────────────────────────────

    async def memory_set(
        self,
        key: str,
        value: str,
        namespace: str = "default",
        ttl_seconds: Optional[int] = None,
    ) -> None:
        body: dict[str, Any] = {"key": key, "value": value, "namespace": namespace}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        await self._request("POST", "/v1/memory", json=body)

    async def memory_get(self, key: str, namespace: str = "default") -> MemoryEntry:
        data = await self._request("GET", f"/v1/memory/{key}", params={"namespace": namespace})
        return MemoryEntry(**data)

    async def memory_list(self, namespace: str = "default", prefix: str = "") -> MemoryListResponse:
        params: dict[str, Any] = {"namespace": namespace}
        if prefix:
            params["prefix"] = prefix
        data = await self._request("GET", "/v1/memory", params=params)
        return MemoryListResponse(**data)

    async def memory_delete(self, key: str, namespace: str = "default") -> None:
        await self._request("DELETE", f"/v1/memory/{key}", params={"namespace": namespace})

    # ── Messaging ──────────────────────────────────────────────────────────────

    async def send_message(self, to_agent: str, payload: str, channel: str = "direct") -> None:
        await self._request(
            "POST",
            "/v1/relay/send",
            json={"to_agent": to_agent, "channel": channel, "payload": payload},
        )

    async def inbox(
        self,
        channel: str = "direct",
        unread_only: bool = True,
        limit: int = 20,
    ) -> InboxResponse:
        data = await self._request(
            "GET",
            "/v1/relay/inbox",
            params={"channel": channel, "unread_only": unread_only, "limit": limit},
        )
        return InboxResponse(**data)

    # ── Queue ──────────────────────────────────────────────────────────────────

    async def queue_submit(
        self,
        payload: Any,
        queue_name: str = "default",
        priority: int = 0,
        max_attempts: int = 1,
    ) -> QueueJob:
        data = await self._request(
            "POST",
            "/v1/queue/submit",
            json={
                "payload": payload,
                "queue_name": queue_name,
                "priority": priority,
                "max_attempts": max_attempts,
            },
        )
        return QueueJob(**data)

    async def queue_claim(self, queue_name: str = "default") -> Optional[QueueJob]:
        data = await self._request("POST", "/v1/queue/claim", params={"queue_name": queue_name})
        if data is None:
            return None
        return QueueJob(**data)

    async def queue_complete(self, job_id: str, result: Optional[str] = None) -> None:
        params: dict[str, Any] = {}
        if result is not None:
            params["result"] = result
        await self._request("POST", f"/v1/queue/{job_id}/complete", params=params)

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    async def heartbeat(self, status: str = "online", metadata: Optional[dict[str, Any]] = None) -> None:
        body: dict[str, Any] = {"status": status}
        if metadata is not None:
            body["metadata"] = metadata
        await self._request("POST", "/v1/agents/heartbeat", json=body)

    # ── Vector Search ──────────────────────────────────────────────────────────

    async def vector_search(
        self,
        query: str,
        namespace: str = "default",
        limit: int = 5,
        min_similarity: float = 0.0,
    ) -> VectorSearchResponse:
        data = await self._request(
            "POST",
            "/v1/vector/search",
            json={
                "query": query,
                "namespace": namespace,
                "limit": limit,
                "min_similarity": min_similarity,
            },
        )
        return VectorSearchResponse(**data)
