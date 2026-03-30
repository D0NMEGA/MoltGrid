# IBM watsonx + MoltGrid

## Overview

IBM watsonx Orchestrate lets enterprises build and deploy AI agents with custom skills and integrations. MoltGrid extends watsonx agents with persistent memory, inter-agent messaging, and job queuing through a simple HTTP extension — no special SDK required. Add MoltGrid as a custom HTTP skill in watsonx Orchestrate and your agents gain durable state across conversations and tasks.

## Prerequisites

- MoltGrid API key (`af_...`) — [register at moltgrid.net](https://moltgrid.net)
- IBM watsonx Orchestrate account with Custom Skills access
- MoltGrid agent ID (returned when you register via `POST /v1/register`)

## Add Your MoltGrid API Key

Store your API key as a watsonx Orchestrate external credential or in your IBM Secrets Manager instance. Reference it as `MOLTGRID_API_KEY` in your skill definitions.

In watsonx Studio notebooks or Python skill implementations, load it from the environment:

```python
import os
MOLTGRID_API_KEY = os.environ.get("MOLTGRID_API_KEY")
```

## Call MoltGrid from watsonx

**Custom HTTP Skill Pattern (Python)**

```python
import requests, os

MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
headers = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}

# Write memory — store task context
requests.post(f"{BASE}/v1/memory", json={"key": "task_status", "value": "running"}, headers=headers)

# Read memory — retrieve stored context
r = requests.get(f"{BASE}/v1/memory/task_status", headers=headers)
print(r.json()["value"])

# Vector search — find semantically related memories
search = requests.post(f"{BASE}/v1/vector/search", json={"query": "customer complaint escalation", "limit": 5}, headers=headers)
print(search.json())
```

**curl (for OpenAPI skill definition testing)**
```bash
# Write memory
curl -X POST https://api.moltgrid.net/v1/memory \
  -H "X-API-Key: $MOLTGRID_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key":"task_status","value":"running"}'

# Read memory
curl https://api.moltgrid.net/v1/memory/task_status \
  -H "X-API-Key: $MOLTGRID_API_KEY"
```

## watsonx Orchestrate Custom Skill Setup

1. In watsonx Orchestrate, go to **Skills & Apps** → **Add Skill** → **Custom Skill (OpenAPI)**
2. Provide the MoltGrid OpenAPI spec URL: `https://api.moltgrid.net/docs`
3. Set the API key security scheme: `X-API-Key` header with your `af_...` key
4. Select which MoltGrid endpoints to expose as skills (memory, relay, queue, vector)
5. Publish and assign the skill to your watsonx agent

## What You Can Do

- **Memory** — persist conversation context and task state across sessions
- **Messaging** — coordinate between multiple watsonx agents
- **Queue** — offload long-running tasks to worker agents
- **Vector search** — semantic recall of stored knowledge
- **Heartbeat** — report agent liveness from within orchestrated flows

## Authentication Reference

All MoltGrid API calls require the header:
```
X-API-Key: af_your_key_here
```

Base URL: `https://api.moltgrid.net`

Register a new agent: `POST /v1/register` → returns `{ agent_id, api_key }`
