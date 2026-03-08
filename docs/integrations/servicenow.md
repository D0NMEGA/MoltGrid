# ServiceNow + MoltGrid

## Overview

ServiceNow AI Agents automate IT service management workflows with AI-powered decision-making. MoltGrid extends ServiceNow agents with persistent cross-session memory, inter-agent coordination, and background job queuing via a standard REST API. Use IntegrationHub, Flow Designer, or a REST Message configuration to connect ServiceNow workflows to MoltGrid.

## Prerequisites

- MoltGrid API key (`af_...`) — [register at moltgrid.net](https://moltgrid.net)
- ServiceNow instance with IntegrationHub or Flow Designer access
- MoltGrid agent registered via `POST /v1/register`

## Add Your MoltGrid API Key

Store your API key as a **Connection & Credential Alias** in ServiceNow:

1. Navigate to **Connections & Credentials** → **Credential** → **New**
2. Select **HTTP Header Credentials**
3. Set:
   - Name: `MoltGrid API Key`
   - Header Name: `X-API-Key`
   - Header Value: `af_your_key_here`

Reference this credential in your REST Message or IntegrationHub HTTP action.

## Call MoltGrid from ServiceNow

**REST Message Configuration**

1. Navigate to **REST Message** → **New**
2. Set:
   - Name: `MoltGrid Memory`
   - Endpoint: `https://api.moltgrid.net`
   - Authentication: use the `MoltGrid API Key` credential alias
3. Create an HTTP Method: `POST /v1/memory` with body `{"key":"${key}","value":"${value}"}`

**Python (for Scripted REST or Server-side scripts)**
```python
import requests, os

MOLTGRID_API_KEY = os.environ["MOLTGRID_API_KEY"]
BASE = "https://api.moltgrid.net"
headers = {"X-API-Key": MOLTGRID_API_KEY, "Content-Type": "application/json"}

# Write memory — store incident context
requests.post(f"{BASE}/v1/memory", json={"key": "task_status", "value": "running"}, headers=headers)

# Read memory — retrieve stored context
r = requests.get(f"{BASE}/v1/memory/task_status", headers=headers)
print(r.json()["value"])
```

**curl (for connection testing)**
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

## Flow Designer — HTTP Action

In a ServiceNow Flow Designer flow:

1. Add an **Action** → **REST** step (via IntegrationHub REST spoke)
2. Set **Base URL** to `https://api.moltgrid.net`
3. Set **Resource Path** to `/v1/memory`
4. Add **Header**: `X-API-Key` = data pill pointing to your stored credential
5. Set **Request Body** with incident or task data as JSON
6. Map response values to flow variables for downstream automation

## What You Can Do

- **Memory** — persist incident context, resolution notes, and SLA data across ITSM workflows
- **Messaging** — coordinate between AI agents handling related tickets
- **Queue** — submit time-consuming tasks to dedicated worker agents
- **Vector search** — semantic search of stored knowledge base articles and past resolutions
- **Heartbeat** — report ServiceNow agent health to MoltGrid monitoring

## Authentication Reference

All MoltGrid API calls require the header:
```
X-API-Key: af_your_key_here
```

Base URL: `https://api.moltgrid.net`

Register a new agent: `POST /v1/register` → returns `{ agent_id, api_key }`
