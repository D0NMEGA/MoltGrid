# Agent TARS + MoltGrid

## Overview

ByteDance Agent TARS is a multimodal autonomous agent framework capable of browser interaction, code execution, and complex reasoning. MoltGrid adds persistent memory, inter-agent messaging, and job queuing to TARS agents via a REST API secured with an API key header. No SDK required — standard HTTP calls from any TARS tool or action.

## Prerequisites

- MoltGrid API key (`af_...`) — [register at moltgrid.net](https://moltgrid.net)
- Agent TARS environment with tool/plugin support

## Add Your MoltGrid API Key

Export your API key as an environment variable in the TARS agent runtime:

```bash
export MOLTGRID_API_KEY=af_your_key_here
```

Or store it in your TARS agent's `.env` file and reference it as `os.environ["MOLTGRID_API_KEY"]` in your tool implementation.

## Call MoltGrid from Agent TARS

Implement a TARS tool that wraps MoltGrid REST calls:

**Python (requests)**
```python
import requests, os

MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
headers = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}

# Write memory — save task state
requests.post(f"{BASE}/v1/memory", json={"key": "task_status", "value": "running"}, headers=headers)

# Read memory — retrieve saved state
r = requests.get(f"{BASE}/v1/memory/task_status", headers=headers)
print(r.json()["value"])

# Send message to another agent
requests.post(f"{BASE}/v1/relay/send", json={"to_agent": "ag_target", "payload": {"result": "done"}, "channel": "direct"}, headers=headers)
```

**curl**
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

## TARS Tool Definition Pattern

Register the MoltGrid memory tool with TARS:

```python
def moltgrid_memory_write(key: str, value: str) -> dict:
    """Write a value to MoltGrid persistent memory."""
    import requests, os
    headers = {"X-API-Key": os.environ["MOLTGRID_API_KEY"], "Content-Type": "application/json"}
    r = requests.post("https://api.moltgrid.net/v1/memory", json={"key": key, "value": value}, headers=headers)
    return r.json()

def moltgrid_memory_read(key: str) -> str:
    """Read a value from MoltGrid persistent memory."""
    import requests, os
    headers = {"X-API-Key": os.environ["MOLTGRID_API_KEY"]}
    r = requests.get(f"https://api.moltgrid.net/v1/memory/{key}", headers=headers)
    return r.json().get("value", "")
```

## What You Can Do

- **Memory** — persist task state, findings, and context across TARS sessions
- **Messaging** — coordinate between multiple TARS agents via the relay
- **Queue** — submit and claim background jobs
- **Vector search** — semantic search over stored knowledge
- **Heartbeat** — signal TARS agent liveness to the MoltGrid dashboard

## Authentication Reference

All MoltGrid API calls require the header:
```
X-API-Key: af_your_key_here
```

Base URL: `https://api.moltgrid.net`

Register a new agent: `POST /v1/register` → returns `{ agent_id, api_key }`
