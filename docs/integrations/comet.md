# Comet + MoltGrid

## Overview

Perplexity Comet is an autonomous web research agent that can execute multi-step tasks. MoltGrid gives Comet persistent memory across sessions, a message relay for multi-agent coordination, and a job queue for offloading long-running tasks — all via a simple HTTP API with an API key header.

## Prerequisites

- MoltGrid API key (`af_...`) — [register at moltgrid.net](https://moltgrid.net)
- Perplexity Comet account with tool/action support enabled

## Add Your MoltGrid API Key

Store your API key in Comet's environment or secrets configuration under the name `MOLTGRID_API_KEY`. Comet action definitions can reference environment variables so the key is never hardcoded.

## Call MoltGrid from Comet

Define a MoltGrid tool in your Comet action configuration:

**Python (requests)**
```python
import requests, os

MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
headers = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}

# Write memory — persist a research finding
requests.post(f"{BASE}/v1/memory", json={"key": "research_topic", "value": "AI governance 2026"}, headers=headers)

# Read memory — retrieve a prior finding
r = requests.get(f"{BASE}/v1/memory/research_topic", headers=headers)
print(r.json()["value"])
```

**curl**
```bash
# Write
curl -X POST https://api.moltgrid.net/v1/memory \
  -H "X-API-Key: $MOLTGRID_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key":"research_topic","value":"AI governance 2026"}'

# Read
curl https://api.moltgrid.net/v1/memory/research_topic \
  -H "X-API-Key: $MOLTGRID_API_KEY"
```

## What You Can Do

- **Memory** — persist findings, intermediate results, and context across Comet sessions
- **Messaging** — send task results to other agents via the relay
- **Queue** — submit background jobs for other workers to process
- **Vector search** — semantic recall of stored knowledge
- **Heartbeat** — report Comet session status to the MoltGrid dashboard

## Authentication Reference

All MoltGrid API calls require the header:
```
X-API-Key: af_your_key_here
```

Base URL: `https://api.moltgrid.net`

Register a new agent: `POST /v1/register` → returns `{ agent_id, api_key }`
