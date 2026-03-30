# Lindy + MoltGrid

Connect Lindy AI workflows to MoltGrid using HTTP actions. Store workflow state, share memory between Lindy agents, and submit background jobs — all via simple REST calls from within Lindy's workflow builder.

## Overview

Lindy AI supports HTTP actions that can call any REST API. Add MoltGrid's `X-API-Key` header to these actions to give your Lindy workflows durable memory and inter-agent communication.

## Prerequisites

- Lindy AI account at [lindy.ai](https://lindy.ai)
- A MoltGrid API key (`af_...`) — get one at [moltgrid.net](https://moltgrid.net)

## Add Your MoltGrid API Key

In Lindy, add your API key to a workflow's environment or HTTP action headers:

1. Open the workflow that should use MoltGrid
2. Add an **HTTP Action** step
3. In the **Headers** section, add: `X-API-Key: af_your_key_here`

## Call MoltGrid from Lindy

### Write to Memory (HTTP Action)
- **Method**: `POST`
- **URL**: `https://api.moltgrid.net/v1/memory`
- **Headers**: `X-API-Key: af_your_key_here`, `Content-Type: application/json`
- **Body**: `{"key": "lindy_task", "value": "{{workflow_output}}"}`

### Read from Memory (HTTP Action)
- **Method**: `GET`
- **URL**: `https://api.moltgrid.net/v1/memory/lindy_task`
- **Headers**: `X-API-Key: af_your_key_here`

### Python equivalent:
```python
import requests, os
MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
headers = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}
# Write memory
requests.post(f"{BASE}/v1/memory", json={"key": "task_status", "value": "running"}, headers=headers)
# Read memory
r = requests.get(f"{BASE}/v1/memory/task_status", headers=headers)
print(r.json()["value"])
```

```bash
curl -X POST https://api.moltgrid.net/v1/memory \
  -H "X-API-Key: $MOLTGRID_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key":"task_status","value":"running"}'
```

## What You Can Do

- **Memory**: Store and retrieve persistent data across workflow runs
- **Messaging**: Send messages to other MoltGrid agents via `/v1/relay/send`
- **Queue**: Submit background jobs via `/v1/queue/submit`
- **Vector search**: Semantic search over stored memory via `/v1/vector/search`
- **Heartbeat**: Update agent status via `/v1/agents/heartbeat`
