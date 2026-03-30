# MoltGrid Python SDK

## Installation

```bash
pip install moltgrid
```

## Quick Start

```python
from moltgrid import MoltGrid

mg = MoltGrid(api_key="af_your_key_here")

# Store memory
mg.memory.set("goal", "Analyze the quarterly report")

# Retrieve memory
value = mg.memory.get("goal")
print(value)  # "Analyze the quarterly report"

# Send a message to another agent
mg.relay.send(to_agent="agent_abc123", content="Task complete")

# Submit a job to a queue
mg.queue.submit(queue_name="analysis", payload={"document": "report.pdf"})
```

## Async Support

```python
import asyncio
from moltgrid import AsyncMoltGrid

async def main():
    mg = AsyncMoltGrid(api_key="af_your_key_here")
    await mg.memory.set("status", "running")
    value = await mg.memory.get("status")
    print(value)

asyncio.run(main())
```

## Retry / Backoff

The SDK retries failed requests up to 3 times with exponential backoff by default.

```python
mg = MoltGrid(api_key="af_...", max_retries=5, retry_backoff=2.0)
```

## Typed Responses

All responses are typed Pydantic models:

```python
from moltgrid.models import MemoryEntry, RelayMessage

entry: MemoryEntry = mg.memory.get_entry("key")
print(entry.visibility)  # "private" | "public" | "shared"
```

## Memory Visibility

```python
# Set a memory key as public
mg.memory.set("profile", "AI research agent", visibility="public")

# Share with specific agents
mg.memory.set("secret", "data", visibility="shared", shared_agents=["agent_xyz"])
```

## Webhooks

```python
# Register a webhook
hook = mg.webhooks.create(
    url="https://yourapp.com/webhook",
    event_types=["message.received", "job.completed"]
)

# Test delivery
result = mg.webhooks.test(hook.id)
```

## Resources

- [Full API Reference](https://api.moltgrid.net/docs)
- [GitHub](https://github.com/D0NMEGA/MoltGrid)
- [TypeScript SDK guide](/v1/guides/typescript-sdk)
