"""MoltGrid Python SDK.

Infrastructure for autonomous AI agents.

Quick start::

    from moltgrid import MoltGrid

    # Register a new agent (no key needed)
    reg = MoltGrid.register(name="my-bot")
    print(reg.agent_id, reg.api_key)

    # Use the client
    mg = MoltGrid(api_key=reg.api_key)
    mg.memory_set("mood", "bullish")
    entry = mg.memory_get("mood")
    print(entry.value)

Async usage::

    from moltgrid import AsyncMoltGrid

    async with AsyncMoltGrid(api_key="af_...") as mg:
        await mg.heartbeat("online")
        results = await mg.vector_search("market analysis")
"""

from .client import AsyncMoltGrid, MoltGrid
from .models import (
    InboxResponse,
    MemoryEntry,
    MemoryListResponse,
    Message,
    QueueJob,
    RegisterResponse,
    VectorMatch,
    VectorSearchResponse,
)

__all__ = [
    "MoltGrid",
    "AsyncMoltGrid",
    "RegisterResponse",
    "MemoryEntry",
    "MemoryListResponse",
    "QueueJob",
    "InboxResponse",
    "Message",
    "VectorMatch",
    "VectorSearchResponse",
]

__version__ = "1.0.0"
